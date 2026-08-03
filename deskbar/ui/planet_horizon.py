"""Runtime compositor for the baked planetary-horizon matte paintings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, TypedDict

import pygame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
ASSET_WIDTH: Final = 1180
VIEWPORT_WIDTH: Final = 1118
BASE_X: Final = -(ASSET_WIDTH - VIEWPORT_WIDTH) // 2
CLOUD_COLORS: Final = {
    "night": (88, 126, 159),
    "dawn": (179, 191, 203),
    "day": (222, 231, 234),
}


@dataclass(frozen=True)
class LightingBlend:
    """Two authored masters and their real-time interpolation amount."""

    __slots__ = ("first", "second", "amount")

    first: str
    second: str
    amount: float


class PlanetHorizonState(TypedDict, total=False):
    """Per-scene caches rebuilt only when the minute-level lighting changes."""

    base_key: tuple[str, str, int]
    base: pygame.Surface
    cloud_key: tuple[int, int, int]
    cloud_far: pygame.Surface
    cloud_near: pygame.Surface


_RAW: dict[str, pygame.Surface] = {}


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


def _load(name: str) -> pygame.Surface:
    surface = _RAW.get(name)
    if surface is None:
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        if pygame.display.get_surface() is not None:
            surface = surface.convert_alpha()
        _RAW[name] = surface
    return surface


def _master(state: PlanetHorizonState, lighting: LightingBlend) -> pygame.Surface:
    step = round(lighting.amount * 60.0)
    key = (lighting.first, lighting.second, step)
    if state.get("base_key") == key:
        return state["base"]
    first = _load(f"planet_horizon_{lighting.first}")
    if lighting.first == lighting.second or step == 0:
        base = first
    else:
        base = pygame.Surface(first.get_size(), pygame.SRCALPHA)
        base.blit(first, (0, 0))
        overlay = _load(f"planet_horizon_{lighting.second}").copy()
        overlay.set_alpha(round(step / 60.0 * 255.0))
        base.blit(overlay, (0, 0))
    state["base_key"], state["base"] = key, base
    return base


def _cloud_color(lighting: LightingBlend) -> tuple[int, int, int]:
    first = CLOUD_COLORS[lighting.first]
    second = CLOUD_COLORS[lighting.second]
    return tuple(round(a + (b - a) * lighting.amount) for a, b in zip(first, second))


def _clouds(state: PlanetHorizonState,
            lighting: LightingBlend) -> tuple[pygame.Surface, pygame.Surface]:
    color = _cloud_color(lighting)
    if state.get("cloud_key") != color:
        for state_key, asset_name in (("cloud_far", "planet_cloud_far"),
                                      ("cloud_near", "planet_cloud_near")):
            tinted = _load(asset_name).copy()
            tinted.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
            state[state_key] = tinted
        state["cloud_key"] = color
    return state["cloud_far"], state["cloud_near"]


def render(panel: pygame.Surface, state: PlanetHorizonState, now: datetime,
           t: float, _dt: float, _weather_code: int | None, _seed: int) -> None:
    """Compose one complete frame from baked masters plus slow cloud parallax."""
    lighting = _lighting(now)
    panel.blit(_master(state, lighting), (BASE_X, 0))
    cloud_far, cloud_near = _clouds(state, lighting)
    far_x = BASE_X + round(math.sin(t * 0.021) * 12.0)
    near_x = BASE_X + round(math.sin(t * 0.013 + 1.7) * 21.0)
    panel.blit(cloud_far, (far_x, 0))
    panel.blit(cloud_near, (near_x, 0))
