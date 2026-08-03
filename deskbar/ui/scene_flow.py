"""Authored luminous fiber-and-ink flow scene."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import MasterBlend, SceneAssets
from deskbar.ui.scene_common import hash_unit
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
BASE_X: Final = -(1240 - 1118) // 2
PARTICLE_COUNT: Final = 48


class FlowParticle:
    __slots__ = ("brush", "phase", "x", "y")

    def __init__(self, x: float, y: float, phase: float, brush: int) -> None:
        self.x = x
        self.y = y
        self.phase = phase
        self.brush = brush


def _lighting(now: datetime) -> tuple[str, str, float]:
    hour = now.hour + now.minute / 60.0
    if 5.0 <= hour < 7.0:
        return "night", "dawn", (hour - 5.0) / 2.0
    if 7.0 <= hour < 8.5:
        return "dawn", "day", (hour - 7.0) / 1.5
    if 8.5 <= hour < 16.5:
        return "day", "day", 0.0
    if 16.5 <= hour < 18.0:
        return "day", "dawn", (hour - 16.5) / 1.5
    if 18.0 <= hour < 20.0:
        return "dawn", "night", (hour - 18.0) / 2.0
    return "night", "night", 0.0


class FlowRenderer:
    """Composite a baked fiber field with bounded authored brush particles."""

    __slots__ = ("_assets", "_brushes", "_particles", "_trail")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._brushes: tuple[pygame.Surface, pygame.Surface] | None = None
        self._particles: list[FlowParticle] = []
        self._trail: pygame.Surface | None = None

    @property
    def decoded_bytes(self) -> int:
        trail_bytes = 0
        if self._trail is not None:
            trail_bytes = self._trail.get_width() * self._trail.get_height() * 4
        return self._assets.decoded_bytes + trail_bytes

    def _initialize(self, panel: pygame.Surface, seed: int) -> None:
        width, height = panel.get_size()
        self._trail = pygame.Surface((width, height), pygame.SRCALPHA)
        raw_brushes = (
            self._assets.load("flow_brush_0"),
            self._assets.load("flow_brush_1"),
        )
        rect = pygame.Rect(1240 // 2 - 48, 472 // 2 - 16, 96, 32)
        self._brushes = (
            raw_brushes[0].subsurface(rect),
            raw_brushes[1].subsurface(rect),
        )
        self._particles = [
            FlowParticle(
                hash_unit(index, seed) * width,
                hash_unit(index, seed, 7) * height,
                hash_unit(index, seed, 3) * math.tau,
                index % 2,
            )
            for index in range(PARTICLE_COUNT)
        ]

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        if self._trail is None or self._brushes is None:
            self._initialize(panel, frame.day_seed)
        trail = self._trail
        brushes = self._brushes
        if trail is None or brushes is None:
            return
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"flow_base_{first}", f"flow_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        veil = self._assets.load("flow_filament_veil")
        veil_x = BASE_X + round(math.sin(frame.t * math.tau / 74.0) * 30.0)
        veil.set_alpha(205)
        panel.blit(veil, (veil_x, 0))
        trail.fill((0, 0, 0, 7), special_flags=pygame.BLEND_RGBA_SUB)
        width, height = panel.get_size()
        for index, particle in enumerate(self._particles):
            angle = (
                math.sin(particle.x * 0.006 + frame.t * 0.12 + particle.phase)
                + math.cos(particle.y * 0.008 - frame.t * 0.09 + particle.phase)
            ) * 1.35
            speed = 12.0 + hash_unit(index, frame.day_seed, 19) * 18.0
            particle.x += math.cos(angle) * speed * frame.dt
            particle.y += math.sin(angle) * speed * frame.dt
            if not 0 <= particle.x < width or not 0 <= particle.y < height:
                particle.x = hash_unit(index, int(frame.t), frame.day_seed) * width
                particle.y = hash_unit(index, int(frame.t), frame.day_seed, 2) * height
            brush = brushes[particle.brush]
            brush.set_alpha(90 + round(hash_unit(index, frame.day_seed, 23) * 100))
            trail.blit(brush, (round(particle.x) - 48, round(particle.y) - 16))
        panel.blit(trail, (0, 0))

    def close(self) -> None:
        self._particles.clear()
        self._brushes = None
        self._trail = None
        self._assets.close()
