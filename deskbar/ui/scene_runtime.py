"""Typed frame data and lifecycle ownership for ambient scene renderers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import pygame


@dataclass(frozen=True)
class SceneFrame:
    """All deterministic inputs needed to render one ambient-scene frame."""

    __slots__ = ("now", "t", "dt", "weather_code", "day_seed")

    now: datetime
    t: float
    dt: float
    weather_code: int | None
    day_seed: int


class SceneRenderer(Protocol):
    """Renderer contract with explicit decoded-asset ownership."""

    @property
    def decoded_bytes(self) -> int:
        """Return the current decoded surface footprint in bytes."""
        ...

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        """Draw one complete frame into the supplied scene panel."""
        ...

    def close(self) -> None:
        """Release all decoded assets owned by this renderer."""
        ...


@dataclass(frozen=True)
class RendererClosedError(RuntimeError):
    """Raised when a closed renderer handle receives more work."""

    __slots__ = ("renderer_name",)

    renderer_name: str

    def __str__(self) -> str:
        return f"scene renderer is closed: {self.renderer_name}"


@dataclass(frozen=True)
class InvalidDecodedBytesError(ValueError):
    """Raised when a renderer violates decoded-byte accounting."""

    __slots__ = ("renderer_name", "decoded_bytes")

    renderer_name: str
    decoded_bytes: int

    def __str__(self) -> str:
        return (
            "scene renderer reported negative decoded bytes: "
            f"{self.renderer_name}={self.decoded_bytes}"
        )


class RendererHandle:
    """Own one active renderer and enforce its close/accounting contract."""

    __slots__ = ("_closed", "_renderer")

    def __init__(self, renderer: SceneRenderer) -> None:
        self._renderer = renderer
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def decoded_bytes(self) -> int:
        if self._closed:
            return 0
        decoded_bytes = self._renderer.decoded_bytes
        if decoded_bytes < 0:
            raise InvalidDecodedBytesError(self._renderer_name, decoded_bytes)
        return decoded_bytes

    @property
    def _renderer_name(self) -> str:
        return self._renderer.__class__.__name__

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        if self._closed:
            raise RendererClosedError(self._renderer_name)
        self._renderer.render(panel, frame)

    def close(self) -> None:
        if self._closed:
            return
        self._renderer.close()
        self._closed = True
