"""Authored atmospheric mountain matte with bounded cached layers."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import MasterBlend, SceneAssets, TintRequest
from deskbar.ui.scene_common import Color, lerp
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
BASE_X: Final = -(1240 - 1118) // 2
TINTS: Final[dict[str, dict[str, Color]]] = {
    "far": {"night": (76, 96, 128), "dawn": (188, 145, 153), "day": (165, 194, 207)},
    "mid": {"night": (44, 59, 82), "dawn": (119, 89, 111), "day": (105, 139, 154)},
    "near": {"night": (19, 28, 42), "dawn": (58, 48, 70), "day": (48, 70, 78)},
}


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


class RidgesRenderer:
    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"ridges_base_{first}", f"ridges_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        layers = (("far", 131.0, 2.0), ("mid", 109.0, 4.0), ("near", 97.0, 6.0))
        for name, period, amplitude in layers:
            color = lerp(TINTS[name][first], TINTS[name][second], amount)
            layer = self._assets.tinted(TintRequest(f"ridges_{name}", color, None))
            offset = round(math.sin(frame.t * math.tau / period + amplitude) * amplitude)
            if name == "far":
                panel.blit(layer, (BASE_X + offset, 0))
                fog = self._assets.load("ridges_fog")
                fog.set_alpha(220)
                fog_x = round(math.sin(frame.t * math.tau / 71.0) * 56.0)
                panel.blit(fog, (BASE_X + fog_x, 0))
            elif name == "mid":
                panel.blit(layer, (BASE_X + offset, 0))
                shadow = self._assets.load("ridges_shadow")
                shadow.set_alpha(190)
                shadow_x = round(math.sin(frame.t * math.tau / 53.0 + 1.4) * 72.0)
                panel.blit(shadow, (BASE_X + shadow_x, 0))
            else:
                panel.blit(layer, (BASE_X + offset, 0))

    def close(self) -> None:
        self._assets.close()
