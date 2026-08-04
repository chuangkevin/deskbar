"""Authored volumetric aurora curtains over a dimensional landscape."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import SceneAssets
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
BASE_X: Final = -(1240 - 1118) // 2
TILE_X: Final = -BASE_X
TILE_WIDTH: Final = 1118


class AuroraRenderer:
    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        panel.blit(self._assets.load("aurora_base_night"), (BASE_X, 0))
        specifications = (
            (0, 7.2, 218, 0.08, 19.0, 0.0),
            (1, 10.6, 238, 0.41, 16.0, 1.8),
            (2, 14.1, 224, 0.72, 13.0, 3.6),
        )
        tile_area = pygame.Rect(TILE_X, 0, TILE_WIDTH, 472)
        for index, speed, base_alpha, start, breathe_period, phase in specifications:
            curtain = self._assets.load(f"aurora_curtain_{index}")
            breathe = math.sin(frame.t * math.tau / breathe_period + phase)
            curtain.set_alpha(round(base_alpha + breathe * 12.0))
            vertical = round(
                math.sin(frame.t * math.tau / (23.0 + index * 4.0) + phase) * 2.0
            )
            left = -round((frame.t * speed + start * TILE_WIDTH) % TILE_WIDTH)
            while left < panel.get_width():
                panel.blit(curtain, (left, vertical), tile_area)
                left += TILE_WIDTH

    def close(self) -> None:
        self._assets.close()
