"""Authored dusk meadow with depth-sorted deterministic fireflies."""

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
FIREFLY_COUNT: Final = 30


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


class FirefliesRenderer:
    __slots__ = ("_assets", "_glows")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._glows: tuple[pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _glow_sprites(self) -> tuple[pygame.Surface, pygame.Surface]:
        if self._glows is None:
            loaded = (
                self._assets.load("fireflies_glow_0"),
                self._assets.load("fireflies_glow_1"),
            )
            sizes = (36, 58)
            self._glows = tuple(
                surface.subsurface(
                    pygame.Rect(1240 // 2 - size // 2, 472 // 2 - size // 2, size, size)
                )
                for surface, size in zip(loaded, sizes)
            )
        return self._glows

    def _draw_fireflies(
        self,
        panel: pygame.Surface,
        frame: SceneFrame,
        near: bool,
    ) -> None:
        glows = self._glow_sprites()
        width, height = panel.get_size()
        for index in range(FIREFLY_COUNT):
            is_near = index % 3 == 0
            if is_near != near:
                continue
            anchor_x = hash_unit(index, frame.day_seed) * width
            anchor_y = height * (0.52 + hash_unit(index, frame.day_seed, 2) * 0.40)
            x = anchor_x + math.sin(frame.t * (0.18 + hash_unit(index, 3) * 0.16) + index) * (54 if near else 34)
            y = anchor_y + math.sin(frame.t * (0.24 + hash_unit(index, 4) * 0.20) + index * 1.8) * (25 if near else 16)
            glow = glows[1 if near else 0]
            breathe = math.sin(frame.t * (0.7 + hash_unit(index, 5))
                                + hash_unit(index, 6) * math.tau)
            alpha = max(0, 125 + round(breathe * 105))
            glow.set_alpha(alpha)
            panel.blit(glow, (round(x) - glow.get_width() // 2,
                              round(y) - glow.get_height() // 2))

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"fireflies_base_{first}", f"fireflies_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        far_grass = self._assets.load("fireflies_grass_far")
        panel.blit(far_grass, (BASE_X + round(math.sin(frame.t * math.tau / 113.0) * 4.0), 0))
        haze = self._assets.load("fireflies_haze")
        haze.set_alpha(165)
        panel.blit(haze, (BASE_X + round(math.sin(frame.t * math.tau / 83.0) * 24.0), 0))
        self._draw_fireflies(panel, frame, near=False)
        near_grass = self._assets.load("fireflies_grass_near")
        panel.blit(near_grass, (BASE_X + round(math.sin(frame.t * math.tau / 97.0) * 7.0), 0))
        self._draw_fireflies(panel, frame, near=True)

    def close(self) -> None:
        self._glows = None
        self._assets.close()
