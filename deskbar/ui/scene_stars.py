"""Authored astrophotographic star field with deterministic parallax and meteors."""

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


def _meteor_age(t: float, seed: int) -> float:
    cycle = int(t // 47.0)
    launch = cycle * 47.0 + hash_unit(cycle, seed, 91) * 40.0
    return t - launch


def meteor_active(t: float, seed: int) -> bool:
    """Return whether the rare deterministic meteor is visible at ``t``."""
    cycle = int(t // 47.0)
    return 0.0 <= _meteor_age(t, seed) <= 1.2 and hash_unit(cycle, seed, 92) > 0.55


class StarsRenderer:
    __slots__ = ("_assets", "_sprites")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._sprites: tuple[pygame.Surface, pygame.Surface, pygame.Surface] | None = None

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    def _star_sprites(self) -> tuple[pygame.Surface, pygame.Surface, pygame.Surface]:
        if self._sprites is None:
            sizes = (16, 24, 32)
            loaded = [self._assets.load(f"stars_sprite_{index}") for index in range(3)]
            self._sprites = tuple(
                surface.subsurface(
                    pygame.Rect(1240 // 2 - size // 2, 472 // 2 - size // 2, size, size)
                )
                for surface, size in zip(loaded, sizes)
            )
        return self._sprites

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        first, second, amount = _lighting(frame.now)
        base = self._assets.blended(
            MasterBlend(f"stars_base_{first}", f"stars_base_{second}", amount)
        )
        panel.blit(base, (BASE_X, 0))
        far = self._assets.load("stars_dust_far")
        near = self._assets.load("stars_dust_near")
        far.set_alpha(150)
        near.set_alpha(175)
        panel.blit(far, (BASE_X + round(math.sin(frame.t * math.tau / 92.0) * 12.0), 0))
        panel.blit(near, (BASE_X + round(math.sin(frame.t * math.tau / 61.0 + 1.2) * 22.0), 0))
        sprites = self._star_sprites()
        width, height = panel.get_size()
        layers = ((18, 0.35, 0), (12, 0.75, 1), (8, 1.45, 2))
        for layer, (count, speed, sprite_index) in enumerate(layers):
            sprite = sprites[sprite_index]
            for index in range(count):
                x = (hash_unit(layer, index, frame.day_seed) * width - frame.t * speed) % width
                y = hash_unit(layer, index, frame.day_seed, 3) * height * 0.82 + 8
                twinkle = math.sin(frame.t * (0.6 + hash_unit(layer, index, 4))
                                    + hash_unit(layer, index, 5) * math.tau)
                sprite.set_alpha(125 + round((twinkle + 1.0) * 55.0))
                panel.blit(sprite, (round(x) - sprite.get_width() // 2,
                                    round(y) - sprite.get_height() // 2))
        if meteor_active(frame.t, frame.day_seed):
            meteor = self._assets.load("stars_meteor")
            age = _meteor_age(frame.t, frame.day_seed)
            meteor.set_alpha(round(255 * (1.0 - age / 1.2)))
            panel.blit(meteor, (BASE_X + round(age * 90.0), 0))

    def close(self) -> None:
        self._sprites = None
        self._assets.close()
