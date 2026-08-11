"""Animated top-down sumi-e koi over a paper and water wash."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import MasterBlend, SceneAssets
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
BASE_X: Final = -(1240 - 1118) // 2
FISH_MOTION: Final = (
    (0.22, 0.34, 0.5, 0.065, 0.13),
    (0.52, 0.58, 2.1, 0.070, 0.15),
    (0.78, 0.40, 4.2, 0.055, 0.12),
)


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


def fish_positions(t: float, width: int, height: int) -> tuple[tuple[float, float], ...]:
    """Keep every koi in the water panel while they follow distinct lazy loops."""
    positions: list[tuple[float, float]] = []
    for x_frac, y_frac, phase, x_amp, y_amp in FISH_MOTION:
        turn = t * 0.32 + phase
        x = width * x_frac + math.sin(turn * 0.86) * width * x_amp
        y = height * y_frac + math.cos(turn) * height * y_amp
        positions.append((x, y))
    return tuple(positions)


class FishRenderer:
    __slots__ = ("_assets", "_fish", "_wakes")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._fish: tuple[
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
        ] | None = None
        self._wakes: tuple[pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _sprites(self) -> tuple[
        tuple[
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
            tuple[pygame.Surface, pygame.Surface, pygame.Surface],
        ],
        tuple[pygame.Surface, pygame.Surface],
    ]:
        if self._fish is None:
            rects = (
                pygame.Rect(138, 71, 220, 330),
                pygame.Rect(510, 71, 220, 330),
                pygame.Rect(882, 71, 220, 330),
            )
            self._fish = tuple(
                tuple(
                    self._assets.load(f"fish_sprite_{index}").subsurface(rect)
                    for index in range(3)
                )
                for rect in rects
            )
        if self._wakes is None:
            self._wakes = tuple(
                self._assets.load(f"fish_wake_{index}").subsurface(
                    pygame.Rect(510, 71, 220, 330)
                )
                for index in range(2)
            )
        return self._fish, self._wakes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"fish_base_{first}", f"fish_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        fish_sprites, wakes = self._sprites()
        width, height = panel.get_size()
        frame_order = (0, 1, 2, 1)
        for index, (frames, (x, y)) in enumerate(zip(fish_sprites, fish_positions(frame.t, width, height))):

            wake = wakes[index % 2]
            wake.set_alpha(175 if index == 0 else 160)
            panel.blit(
                wake,
                (round(x) - wake.get_width() // 2, round(y) - wake.get_height() // 2),
            )

            animation_index = frame_order[int(frame.t * (4.5 + index * 0.4) + index) % 4]
            fish = frames[animation_index]
            fish.set_alpha(238 if (frame.weather_code or 0) <= 2 else 194)
            panel.blit(
                fish,
                (round(x) - fish.get_width() // 2, round(y) - fish.get_height() // 2),
            )

    def close(self) -> None:
        self._fish = None
        self._wakes = None
        self._assets.close()
