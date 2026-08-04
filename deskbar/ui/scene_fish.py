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


class FishRenderer:
    __slots__ = ("_assets", "_fish", "_wakes")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._fish: tuple[
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
        ],
        tuple[pygame.Surface, pygame.Surface],
    ]:
        if self._fish is None:
            rects = (
                pygame.Rect(round(1240 * 0.28) - 110, 472 // 2 - 165, 220, 330),
                pygame.Rect(round(1240 * 0.72) - 110, 472 // 2 - 165, 220, 330),
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
                    pygame.Rect(1240 // 2 - 50, 472 // 2 - 140, 100, 280)
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
        margin = 170.0
        cycle = height + margin * 2.0
        progress = (frame.t * 32.0 / cycle) % 1.0
        for index, frames in enumerate(fish_sprites):
            path = progress if index == 0 else (progress + 0.5) % 1.0
            x = width * (0.66 if index == 0 else 0.34) \
                + math.sin(path * math.tau + index * 1.4) * width * 0.07
            y = (height + margin - path * cycle) if index == 0 \
                else (-margin + path * cycle)
            wake = wakes[index % 2]
            wake.set_alpha(82 if index == 0 else 68)
            panel.blit(wake, (round(x) - wake.get_width() // 2,
                              round(y) - wake.get_height() // 2))
            animation_index = frame_order[int(frame.t * (4.5 + index * 0.4) + index) % 4]
            fish = frames[animation_index]
            fish.set_alpha(238 if (frame.weather_code or 0) <= 2 else 194)
            panel.blit(fish, (round(x) - fish.get_width() // 2,
                              round(y) - fish.get_height() // 2))

    def close(self) -> None:
        self._fish = None
        self._wakes = None
        self._assets.close()
