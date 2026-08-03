"""Original cinematic pixel-train window world using integer blits only."""

from __future__ import annotations

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
        panel.blit(far, (BASE_X - int(frame.t * 1.3) % 24, 0))
        panel.blit(mid, (BASE_X - int(frame.t * 2.7) % 46, 0))
        panel.blit(near, (BASE_X - int(frame.t * 3.4) % 60, 0))
        reflection = self._assets.load("train_window_reflection")
        reflection.set_alpha(155)
        panel.blit(reflection, (BASE_X, 0))

    def close(self) -> None:
        self._assets.close()
