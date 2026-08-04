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
FOG_WRAP: Final = 112.0
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


def _weather_layers(weather_code: int | None) -> tuple[int, int, int]:
    """Return fog, foreground haze, and cloud-shadow opacity for WMO weather."""
    if weather_code in (0, 1):
        return 38, 0, 36
    if weather_code in (2, 3):
        return 138, 44, 138
    if weather_code in (45, 48):
        return 225, 100, 108
    if weather_code is not None and weather_code >= 50:
        return 205, 84, 190
    return 122, 38, 124


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
        fog_opacity, haze_opacity, shadow_opacity = _weather_layers(frame.weather_code)
        fog = self._assets.load("ridges_fog")
        fog_breath = 0.985 + math.sin(frame.t * math.tau / 23.0) * 0.015
        fog_x = BASE_X + round((frame.t * 2.8) % FOG_WRAP - FOG_WRAP / 2.0)

        for name in ("far", "mid", "near"):
            color = lerp(TINTS[name][first], TINTS[name][second], amount)
            layer = self._assets.tinted(TintRequest(f"ridges_{name}", color, None))
            if name == "far":
                panel.blit(layer, (BASE_X, 0))
                fog.set_alpha(round(fog_opacity * fog_breath))
                panel.blit(fog, (fog_x, 0))
            elif name == "mid":
                panel.blit(layer, (BASE_X, 0))
                shadow = self._assets.load("ridges_shadow")
                shadow_breath = 0.99 + math.sin(frame.t * math.tau / 31.0 + 1.4) * 0.01
                shadow.set_alpha(round(shadow_opacity * shadow_breath))
                panel.blit(shadow, (BASE_X, 0))
                if haze_opacity:
                    haze_x = BASE_X + round(
                        (frame.t * 1.9 + FOG_WRAP * 0.37) % FOG_WRAP - FOG_WRAP / 2.0
                    )
                    fog.set_alpha(round(haze_opacity * fog_breath))
                    panel.blit(fog, (haze_x, 0))
            else:
                panel.blit(layer, (BASE_X, 0))

    def close(self) -> None:
        self._assets.close()
