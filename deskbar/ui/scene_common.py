"""Shared deterministic math and legacy asset seams for scene renderers."""

from __future__ import annotations

from datetime import datetime
from typing import Final

import pygame

from deskbar.ui import theme


Color = tuple[int, int, int]
PIXEL_SCALE: Final = 4
SKY_STOPS: Final[dict[str, Color]] = {
    "night": (16, 20, 44),
    "dawn": (232, 150, 96),
    "day": (120, 170, 220),
    "dusk": (226, 120, 84),
}

def hash_unit(*values: int | float) -> float:
    """Map deterministic numeric inputs into the half-open range [0, 1)."""
    value = 0x9E3779B9
    for item in values:
        value = (value ^ (int(item) & 0xFFFFFFFF)) * 2654435761 & 0xFFFFFFFF
        value ^= value >> 15
    return ((value * 2246822519 & 0xFFFFFFFF) >> 8) / float(1 << 24)


def lerp(first: Color, second: Color, amount: float) -> Color:
    """Interpolate two RGB colors with a clamped amount."""
    amount = max(0.0, min(1.0, amount))
    return tuple(
        round(first[index] + (second[index] - first[index]) * amount)
        for index in range(3)
    )


def mix(color: Color, alpha: int) -> Color:
    """Composite a color over the current flat theme background."""
    return lerp(theme.C["bg"], color, alpha / 255.0)


def day_seed(now: datetime) -> int:
    return now.year * 400 + now.timetuple().tm_yday


def hour_ramp(
    now: datetime,
    night: Color,
    dawn: Color,
    day: Color,
    dusk: Color,
) -> Color:
    """Interpolate the legacy night/dawn/day/dusk color anchors."""
    hour = now.hour + now.minute / 60.0
    spans = (
        (5.0, 7.0, night, dawn),
        (7.0, 8.5, dawn, day),
        (16.5, 18.0, day, dusk),
        (18.0, 20.0, dusk, night),
    )
    for lower, upper, first, second in spans:
        if lower <= hour < upper:
            return lerp(first, second, (hour - lower) / (upper - lower))
    return day if 8.5 <= hour < 16.5 else night


def pixel_sky(surface: pygame.Surface, now: datetime) -> None:
    """Draw the legacy three-band pixel-art sky."""
    width, height = surface.get_size()
    top = hour_ramp(now, *(SKY_STOPS[key] for key in ("night", "dawn", "day", "dusk")))
    bottom = lerp(top, (255, 244, 214), 0.35)
    for index in range(3):
        surface.fill(
            lerp(top, bottom, index / 2),
            pygame.Rect(0, height * index // 3, width, height // 3 + 1),
        )
