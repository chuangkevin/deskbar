"""Authored luminous fiber-and-ink flow scene."""

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
PARTICLE_COUNT: Final = 48
FLOW_CURVE: Final = (
    (-0.08, 0.32),
    (0.12, 0.12),
    (0.28, 0.16),
    (0.43, 0.55),
    (0.58, 0.94),
    (0.75, 0.82),
    (1.08, 0.37),
)
ASSET_WIDTH: Final = 1240


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


def _cubic_pose(
    points: tuple[tuple[float, float], ...],
    amount: float,
) -> tuple[float, float, float, float]:
    inverse = 1.0 - amount
    x = (
        inverse ** 3 * points[0][0]
        + 3.0 * inverse ** 2 * amount * points[1][0]
        + 3.0 * inverse * amount ** 2 * points[2][0]
        + amount ** 3 * points[3][0]
    )
    y = (
        inverse ** 3 * points[0][1]
        + 3.0 * inverse ** 2 * amount * points[1][1]
        + 3.0 * inverse * amount ** 2 * points[2][1]
        + amount ** 3 * points[3][1]
    )
    dx = 3.0 * (
        inverse ** 2 * (points[1][0] - points[0][0])
        + 2.0 * inverse * amount * (points[2][0] - points[1][0])
        + amount ** 2 * (points[3][0] - points[2][0])
    )
    dy = 3.0 * (
        inverse ** 2 * (points[1][1] - points[0][1])
        + 2.0 * inverse * amount * (points[2][1] - points[1][1])
        + amount ** 2 * (points[3][1] - points[2][1])
    )
    return x, y, dx, dy


def _stream_pose(
    progress: float,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    """Sample the baked S-current and its unit normal in panel coordinates."""
    if progress < 0.5:
        x, y, dx, dy = _cubic_pose(FLOW_CURVE[:4], progress * 2.0)
    else:
        x, y, dx, dy = _cubic_pose(FLOW_CURVE[3:], (progress - 0.5) * 2.0)
    overscan = (ASSET_WIDTH - width) * 0.5
    screen_dx = dx * ASSET_WIDTH
    screen_dy = dy * height
    length = math.hypot(screen_dx, screen_dy)
    normal_x = -screen_dy / length
    normal_y = screen_dx / length
    return x * ASSET_WIDTH - overscan, y * height, normal_x, normal_y


class FlowRenderer:
    """Composite one baked ink current with closed-form traveling fibers."""

    __slots__ = ("_assets", "_brushes")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._brushes: tuple[pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _load_brushes(self) -> tuple[pygame.Surface, pygame.Surface]:
        if self._brushes is not None:
            return self._brushes
        raw_brushes = (
            self._assets.load("flow_brush_0"),
            self._assets.load("flow_brush_1"),
        )
        self._brushes = (
            raw_brushes[0].subsurface(
                pygame.Rect(1240 // 2 - 78, 472 // 2 - 20, 156, 40)
            ),
            raw_brushes[1].subsurface(
                pygame.Rect(1240 // 2 - 56, 472 // 2 - 15, 112, 30)
            ),
        )
        return self._brushes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"flow_base_{first}", f"flow_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        veil = self._assets.load("flow_filament_veil")
        veil.set_alpha(214)
        panel.blit(veil, (BASE_X, 0))
        brushes = self._load_brushes()
        width, height = panel.get_size()
        for index in range(PARTICLE_COUNT):
            speed = 0.011 + hash_unit(index, frame.day_seed, 19) * 0.010
            progress = (hash_unit(index, frame.day_seed, 3) + frame.t * speed) % 1.0
            x, y, normal_x, normal_y = _stream_pose(progress, width, height)
            lane = (
                (hash_unit(index, frame.day_seed, 7) * 2.0 - 1.0)
                * height
                * 0.105
            )
            x += normal_x * lane
            y += normal_y * lane
            angle = math.degrees(math.atan2(-normal_x, normal_y))
            brush_index = 0 if hash_unit(index, frame.day_seed, 13) > 0.84 else 1
            scale = 0.92 + hash_unit(index, frame.day_seed, 17) * 0.42
            fiber = pygame.transform.rotozoom(brushes[brush_index], -angle, scale)
            fiber.set_alpha(92 + round(hash_unit(index, frame.day_seed, 23) * 100))
            panel.blit(fiber, fiber.get_rect(center=(round(x), round(y))))

    def close(self) -> None:
        self._brushes = None
        self._assets.close()
