"""Bake small neutral Sense-weather support sprites used outside scene rotation."""

from __future__ import annotations

from pathlib import Path

import pygame


def _cloud(path: Path, variant: int) -> None:
    surface = pygame.Surface((240, 132), pygame.SRCALPHA)
    centers = ((72, 78, 48), (119, 57, 58), (169, 78, 45))
    for center_x, center_y, radius in centers:
        radius += variant * 2
        for inset in range(radius, 0, -1):
            alpha = round(210 * (1.0 - inset / (radius + 1)) + 20)
            shade = round(188 + 62 * (1.0 - center_y / 132) + inset / radius * 4)
            pygame.draw.circle(surface, (shade, shade, min(255, shade + 4), alpha),
                               (center_x, center_y), inset)
    pygame.image.save(surface, path)


def _sun(path: Path) -> None:
    surface = pygame.Surface((160, 160), pygame.SRCALPHA)
    for radius in range(70, 0, -1):
        distance = radius / 70.0
        alpha = round(50 + (1.0 - distance) * 205)
        shade = round(232 + (1.0 - distance) * 23)
        pygame.draw.circle(surface, (shade, shade, shade, alpha), (80, 80), radius)
    pygame.image.save(surface, path)


def generate_weather_support_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _cloud(out / "cumulus_0.png", 0)
    _cloud(out / "cumulus_1.png", 1)
    _sun(out / "sun_ball.png")
