"""Authored sumi-e fish with paper wash, wakes, and bounded trails."""

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
        self._fish: tuple[pygame.Surface, pygame.Surface, pygame.Surface] | None = None
        self._wakes: tuple[pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _sprites(self) -> tuple[
        tuple[pygame.Surface, pygame.Surface, pygame.Surface],
        tuple[pygame.Surface, pygame.Surface],
    ]:
        if self._fish is None:
            self._fish = tuple(
                self._assets.load(f"fish_sprite_{index}").subsurface(
                    pygame.Rect(1240 // 2 - 110, 472 // 2 - 50, 220, 100)
                )
                for index in range(3)
            )
        if self._wakes is None:
            self._wakes = tuple(
                self._assets.load(f"fish_wake_{index}").subsurface(
                    pygame.Rect(1240 // 2 - 130, 472 // 2 - 42, 260, 84)
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
        depth = 0.30 if (frame.weather_code or 0) <= 2 else 0.62
        for index, fish in enumerate(fish_sprites):
            speed = 22.0 + index * 8.0
            x = (hash_unit(index, frame.day_seed) * (width + 260) + frame.t * speed) \
                % (width + 260) - 130
            y = height * depth + math.sin(frame.t * (0.10 + index * 0.018) + index * 2.2) \
                * height * 0.10 + index * 36 - 36
            wake = wakes[index % 2]
            wake.set_alpha(105)
            panel.blit(wake, (round(x) - 150, round(y) - wake.get_height() // 2))
            for trail_index, alpha in ((2, 42), (1, 74)):
                fish.set_alpha(alpha)
                panel.blit(
                    fish,
                    (round(x - speed * trail_index * 0.12) - fish.get_width() // 2,
                     round(y) - fish.get_height() // 2),
                )
            fish.set_alpha(220)
            panel.blit(fish, (round(x) - fish.get_width() // 2,
                              round(y) - fish.get_height() // 2))

    def close(self) -> None:
        self._fish = None
        self._wakes = None
        self._assets.close()
