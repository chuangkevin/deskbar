"""Per-renderer lazy ownership for decoded cinematic scene assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pygame


DEFAULT_BYTE_LIMIT: Final = 48 * 1024 * 1024
DERIVED_CACHE_LIMIT: Final = 8


@dataclass(frozen=True)
class TintRequest:
    __slots__ = ("name", "color", "size")

    name: str
    color: tuple[int, int, int]
    size: tuple[int, int] | None


@dataclass(frozen=True)
class MasterBlend:
    __slots__ = ("first", "second", "amount")

    first: str
    second: str
    amount: float


@dataclass(frozen=True)
class SceneAssetsClosedError(RuntimeError):
    __slots__ = ("asset_dir",)

    asset_dir: Path

    def __str__(self) -> str:
        return f"scene assets already closed: {self.asset_dir}"


@dataclass(frozen=True)
class AssetMemoryLimitError(MemoryError):
    __slots__ = ("byte_limit", "projected_bytes")

    byte_limit: int
    projected_bytes: int

    def __str__(self) -> str:
        return (
            "scene decoded-asset limit exceeded: "
            f"{self.projected_bytes} > {self.byte_limit} bytes"
        )


class SceneAssets:
    """Own lazy raw and derived surfaces for exactly one active renderer."""

    __slots__ = ("_asset_dir", "_byte_limit", "_closed", "_derived", "_raw")

    def __init__(self, asset_dir: Path, byte_limit: int = DEFAULT_BYTE_LIMIT) -> None:
        self._asset_dir = asset_dir
        self._byte_limit = byte_limit
        self._closed = False
        self._raw: dict[str, pygame.Surface] = {}
        self._derived: dict[str, pygame.Surface] = {}

    @property
    def decoded_bytes(self) -> int:
        surfaces = {
            id(surface): surface
            for surface in (*self._raw.values(), *self._derived.values())
        }
        return sum(
            surface.get_width() * surface.get_height() * 4
            for surface in surfaces.values()
        )

    def _require_open(self) -> None:
        if self._closed:
            raise SceneAssetsClosedError(self._asset_dir)

    def _check_capacity(self, surface: pygame.Surface) -> None:
        projected = (
            self.decoded_bytes
            + surface.get_width() * surface.get_height() * 4
        )
        if projected > self._byte_limit:
            raise AssetMemoryLimitError(self._byte_limit, projected)

    def _remember_derived(self, key: str, surface: pygame.Surface) -> pygame.Surface:
        while len(self._derived) >= DERIVED_CACHE_LIMIT:
            oldest = next(iter(self._derived))
            del self._derived[oldest]
        self._check_capacity(surface)
        self._derived[key] = surface
        return surface

    def load(self, name: str) -> pygame.Surface:
        self._require_open()
        cached = self._raw.get(name)
        if cached is not None:
            return cached
        surface = pygame.image.load(str(self._asset_dir / f"{name}.png"))
        if pygame.display.get_surface() is not None:
            surface = surface.convert_alpha()
        self._check_capacity(surface)
        self._raw[name] = surface
        return surface

    def tinted(self, request: TintRequest) -> pygame.Surface:
        self._require_open()
        key = f"tint:{request.name}:{request.color}:{request.size}"
        cached = self._derived.get(key)
        if cached is not None:
            return cached
        raw = self.load(request.name)
        surface = (
            pygame.transform.smoothscale(raw, request.size)
            if request.size is not None
            else raw.copy()
        )
        surface.fill((*request.color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        return self._remember_derived(key, surface)

    def blended(self, request: MasterBlend) -> pygame.Surface:
        self._require_open()
        step = round(max(0.0, min(1.0, request.amount)) * 60.0)
        if request.first == request.second or step == 0:
            return self.load(request.first)
        key = f"blend:{request.first}:{request.second}:{step}"
        cached = self._derived.get(key)
        if cached is not None:
            return cached
        first = self.load(request.first)
        second = self.load(request.second)
        surface = pygame.Surface(first.get_size(), pygame.SRCALPHA)
        surface.blit(first, (0, 0))
        overlay = second.copy()
        overlay.set_alpha(round(step / 60.0 * 255.0))
        surface.blit(overlay, (0, 0))
        return self._remember_derived(key, surface)

    def close(self) -> None:
        if self._closed:
            return
        self._derived.clear()
        self._raw.clear()
        self._closed = True
