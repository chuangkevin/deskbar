"""Authored paper and cached quantized pigment-bloom renderer."""

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
STAGE_COUNT: Final = 8


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


class InkRenderer:
    __slots__ = ("_assets", "_scaled")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._scaled: dict[tuple[int, int], pygame.Surface] = {}

    @property
    def scaled_cache_entries(self) -> int:
        return len(self._scaled)

    @property
    def decoded_bytes(self) -> int:
        scaled_bytes = sum(
            surface.get_width() * surface.get_height() * 4
            for surface in self._scaled.values()
        )
        return self._assets.decoded_bytes + scaled_bytes

    def _bloom(self, mask_index: int, stage: int) -> pygame.Surface:
        key = (mask_index, stage)
        cached = self._scaled.get(key)
        if cached is not None:
            return cached
        source = self._assets.load(f"ink_bloom_{mask_index}").subsurface(
            pygame.Rect(1240 // 2 - 160, 472 // 2 - 160, 320, 320)
        )
        size = 48 + stage * 32
        cached = pygame.transform.smoothscale(source, (size, size))
        self._scaled[key] = cached
        return cached

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"ink_base_{first}", f"ink_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        width, height = panel.get_size()
        life, interval = 18.0, 6.0
        for index in range(6):
            born = (int(frame.t // interval) - index) * interval \
                + hash_unit(index, frame.day_seed) * 3.0
            age = frame.t - born
            if not 0.0 <= age <= life:
                continue
            progress = min(1.0, age / 9.0)
            stage = min(STAGE_COUNT - 1, int(progress * STAGE_COUNT))
            bloom = self._bloom(index % 3, stage)
            fade = min(age / 1.5, (life - age) / 5.0, 1.0)
            bloom.set_alpha(max(0, round(210 * fade)))
            identity = int(born)
            x = hash_unit(identity, frame.day_seed, 1) * (width - 180) + 90
            y = hash_unit(identity, frame.day_seed, 2) * (height - 160) + 80
            sway = math.sin(frame.t * 0.08 + identity) * 8.0
            panel.blit(bloom, (round(x + sway) - bloom.get_width() // 2,
                               round(y) - bloom.get_height() // 2))

    def close(self) -> None:
        self._scaled.clear()
        self._assets.close()
