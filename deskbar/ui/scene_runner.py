"""Original pixel adventurer in an authored multi-plane world."""

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


def obstacle_phase(t: float, seed: int) -> int:
    """Return a deterministic integer obstacle phase for jump timing."""
    return (int(t * 18.0) + seed % 97) % 146


class RunnerRenderer:
    __slots__ = ("_assets", "_frames")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._frames: tuple[pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _runner_frames(self) -> tuple[pygame.Surface, pygame.Surface]:
        if self._frames is None:
            sheet = self._assets.load("runner_sprite_sheet")
            self._frames = (
                sheet.subsurface(pygame.Rect(564, 212, 32, 44)),
                sheet.subsurface(pygame.Rect(644, 212, 32, 44)),
            )
        return self._frames

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"runner_base_{first}", f"runner_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        panel.blit(self._assets.load("runner_far"), (BASE_X - int(frame.t * 0.8) % 20, 0))
        panel.blit(self._assets.load("runner_mid"), (BASE_X - int(frame.t * 1.8) % 42, 0))
        panel.blit(self._assets.load("runner_near"), (BASE_X - int(frame.t * 3.2) % 58, 0))
        phase = obstacle_phase(frame.t, frame.day_seed)
        obstacles = self._assets.load("runner_obstacles")
        panel.blit(obstacles, (BASE_X - phase, 0))
        jump = math.sin(phase / 34.0 * math.pi) * 58.0 if phase < 34 else 0.0
        runner = self._runner_frames()[int(frame.t * 7.0) % 2]
        panel.blit(runner, (150, round(334 - jump)))

    def close(self) -> None:
        self._frames = None
        self._assets.close()
