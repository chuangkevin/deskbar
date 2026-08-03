"""Layered orbital planet-horizon compositor with deterministic motion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import MasterBlend, SceneAssets
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
ASSET_WIDTH: Final = 1240
VIEWPORT_WIDTH: Final = 1118
BASE_X: Final = -(ASSET_WIDTH - VIEWPORT_WIDTH) // 2


@dataclass(frozen=True)
class LightingBlend:
    __slots__ = ("first", "second", "amount")

    first: str
    second: str
    amount: float


@dataclass(frozen=True)
class PlanetMotion:
    __slots__ = (
        "body_x",
        "body_y",
        "far_cloud_x",
        "near_cloud_x",
        "rim_alpha",
        "haze_alpha",
    )

    body_x: int
    body_y: int
    far_cloud_x: int
    near_cloud_x: int
    rim_alpha: float
    haze_alpha: float


def _wave(t: float, period: float) -> float:
    return math.sin(t * math.tau / period)


def motion_at(t: float) -> PlanetMotion:
    """Return the approved medium-cinematic motion contract at time ``t``."""
    return PlanetMotion(
        body_x=round(_wave(t, 96.0) * 16.0),
        body_y=round(_wave(t, 73.0) * 6.0),
        far_cloud_x=round(_wave(t, 74.0) * 28.0),
        near_cloud_x=round(_wave(t, 49.0) * 48.0),
        rim_alpha=1.0 + _wave(t, 16.0) * 0.08,
        haze_alpha=1.0 + _wave(t, 21.0) * 0.10,
    )


def _lighting(now: datetime) -> LightingBlend:
    hour = now.hour + now.minute / 60.0
    if 5.0 <= hour < 7.0:
        return LightingBlend("night", "dawn", (hour - 5.0) / 2.0)
    if 7.0 <= hour < 8.5:
        return LightingBlend("dawn", "day", (hour - 7.0) / 1.5)
    if 8.5 <= hour < 16.5:
        return LightingBlend("day", "day", 0.0)
    if 16.5 <= hour < 18.0:
        return LightingBlend("day", "dawn", (hour - 16.5) / 1.5)
    if 18.0 <= hour < 20.0:
        return LightingBlend("dawn", "night", (hour - 18.0) / 2.0)
    return LightingBlend("night", "night", 0.0)


def _layer_blend(assets: SceneAssets, layer: str, lighting: LightingBlend) -> pygame.Surface:
    return assets.blended(
        MasterBlend(
            f"planet_{layer}_{lighting.first}",
            f"planet_{layer}_{lighting.second}",
            lighting.amount,
        )
    )


class PlanetHorizonRenderer:
    """Own and composite independently authored planet, cloud, rim, and haze layers."""

    __slots__ = ("_assets",)

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        lighting = _lighting(frame.now)
        motion = motion_at(frame.t)
        panel.blit(_layer_blend(self._assets, "sky", lighting), (BASE_X, 0))
        body_position = (BASE_X + motion.body_x, motion.body_y)
        panel.blit(_layer_blend(self._assets, "body", lighting), body_position)
        rim = _layer_blend(self._assets, "rim", lighting)
        rim.set_alpha(round(230 * motion.rim_alpha))
        panel.blit(rim, body_position)
        far_cloud = self._assets.load("planet_cloud_far")
        panel.blit(far_cloud, (BASE_X + motion.far_cloud_x, 0))
        haze = self._assets.load("planet_haze")
        haze.set_alpha(round(180 * motion.haze_alpha))
        panel.blit(haze, (BASE_X, 0))
        near_cloud = self._assets.load("planet_cloud_near")
        panel.blit(near_cloud, (BASE_X + motion.near_cloud_x, 0))

    def close(self) -> None:
        self._assets.close()
