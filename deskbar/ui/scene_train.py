"""Original cinematic pixel-train window world using integer blits only."""

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
TILE_PERIOD: Final = 1236
LAYER_SPEEDS: Final = (40.0, 96.0, 240.0)


def _lighting(now: datetime) -> tuple[str, str, float]:
    """Follow the current local clock with seasonally plausible twilight."""
    day = now.timetuple().tm_yday
    summer = math.cos(math.tau * (day - 172) / 365.2425)
    daylight_hours = 12.15 + 1.55 * summer
    sunrise = 12.0 - daylight_hours / 2.0
    sunset = 12.0 + daylight_hours / 2.0
    hour = (
        now.hour
        + now.minute / 60.0
        + now.second / 3600.0
        + now.microsecond / 3_600_000_000.0
    )

    def blend(start: float, end: float) -> float:
        amount = max(0.0, min(1.0, (hour - start) / (end - start)))
        return amount * amount * (3.0 - 2.0 * amount)

    if sunrise - 1.0 <= hour < sunrise:
        return "night", "dawn", blend(sunrise - 1.0, sunrise)
    if sunrise <= hour < sunrise + 1.25:
        return "dawn", "day", blend(sunrise, sunrise + 1.25)
    if sunrise + 1.25 <= hour < sunset - 1.25:
        return "day", "day", 0.0
    if sunset - 1.25 <= hour < sunset:
        return "day", "dawn", blend(sunset - 1.25, sunset)
    if sunset <= hour < sunset + 1.0:
        return "dawn", "night", blend(sunset, sunset + 1.0)
    return "night", "night", 0.0


def _blit_wrapped(
    panel: pygame.Surface,
    layer: pygame.Surface,
    distance: float,
) -> None:
    """Tile one authored cycle with its transparent edge pixels overlapped."""
    x = BASE_X - (round(distance) % TILE_PERIOD)
    while x + layer.get_width() <= 0:
        x += TILE_PERIOD
    while x < panel.get_width():
        panel.blit(layer, (x, 0))
        x += TILE_PERIOD


class TrainRenderer:
    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"train_base_{first}", f"train_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        far = self._assets.load("train_far")
        mid = self._assets.load("train_mid")
        near = self._assets.load("train_near")
        _blit_wrapped(panel, far, frame.t * LAYER_SPEEDS[0])
        _blit_wrapped(panel, mid, frame.t * LAYER_SPEEDS[1])
        _blit_wrapped(panel, near, frame.t * LAYER_SPEEDS[2])
        reflection = self._assets.load("train_window_reflection")
        panel.blit(reflection, (BASE_X, 0))

    def close(self) -> None:
        self._assets.close()
