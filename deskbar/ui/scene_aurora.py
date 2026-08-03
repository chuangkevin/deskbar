"""Authored volumetric aurora curtains over a dimensional landscape."""

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


class AuroraRenderer:
    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"aurora_base_{first}", f"aurora_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        specifications = (
            (0, 104.0, 16.0, 175, 0.0),
            (1, 79.0, 26.0, 160, 1.8),
            (2, 61.0, 38.0, 145, 3.6),
        )
        for index, period, amplitude, base_alpha, phase in specifications:
            curtain = self._assets.load(f"aurora_curtain_{index}")
            offset = round(math.sin(frame.t * math.tau / period + phase) * amplitude)
            breathe = math.sin(frame.t * math.tau / (17.0 + index * 3.0) + phase)
            curtain.set_alpha(base_alpha + round(breathe * 28.0))
            panel.blit(curtain, (BASE_X + offset, 0))

    def close(self) -> None:
        self._assets.close()
