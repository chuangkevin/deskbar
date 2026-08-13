"""A small, reusable rain-on-glass layer for central ambient scenes.

The layer intentionally owns only a few tiny alpha sprites.  Allocating a
1118×472 transparent surface every ambient frame is both visually unnecessary
and needlessly expensive on the Pi; water is sparse, so blitting individual
droplets gives a cleaner result and bounds memory/CPU cost.
"""

from __future__ import annotations

import math
from typing import Final

import pygame

from deskbar.ui.scene_common import hash_unit
from deskbar.ui.scene_runtime import SceneFrame
from deskbar.ui.weatherfx import RAIN_CODES, THUNDER_CODES


_DROP_DIAMETERS: Final = (13, 19, 27)
_DROP_SPRITES: dict[int, pygame.Surface] = {}
_TRAIL_SPRITES: dict[int, pygame.Surface] = {}


def _drop_sprite(diameter: int) -> pygame.Surface:
    """Return a zero-edged, lens-like droplet sprite from a bounded cache."""
    sprite = _DROP_SPRITES.get(diameter)
    if sprite is not None:
        return sprite
    pad = 4
    width = diameter + pad * 2
    height = round(diameter * 1.22) + pad * 2
    sprite = pygame.Surface((width, height), pygame.SRCALPHA)
    lens = pygame.Rect(pad, pad, diameter, height - pad * 2)
    # A dark lower rim, cool transparent lens, and small upper-left specular
    # spot make this read as water, not as a pale disc or square overlay.
    pygame.draw.ellipse(sprite, (5, 22, 28, 132), lens.move(1, 2))
    pygame.draw.ellipse(sprite, (122, 196, 210, 74), lens)
    pygame.draw.ellipse(sprite, (204, 244, 250, 162), lens.inflate(-4, -5), 1)
    highlight = pygame.Rect(
        pad + round(diameter * 0.20), pad + round((height - pad * 2) * 0.20),
        max(2, round(diameter * 0.27)), max(2, round((height - pad * 2) * 0.19)),
    )
    pygame.draw.ellipse(sprite, (245, 255, 255, 220), highlight)
    _DROP_SPRITES[diameter] = sprite
    return sprite


def _trail_sprite(head_diameter: int) -> pygame.Surface:
    """A continuous, tapering tail with completely transparent outer edges."""
    sprite = _TRAIL_SPRITES.get(head_diameter)
    if sprite is not None:
        return sprite
    width = max(7, head_diameter + 2)
    height = 64
    sprite = pygame.Surface((width, height), pygame.SRCALPHA)
    center = width // 2
    # Build a gently widening wet trail; overlapping short strokes create an
    # unbroken taper rather than a dotted rain line.
    for y in range(3, height - 4):
        progress = y / height
        half_width = max(1, round((1.0 - progress) * 1.5))
        alpha = round((1.0 - progress) ** 1.8 * 76)
        pygame.draw.line(sprite, (130, 205, 218, alpha),
                         (center - half_width, y), (center + half_width, y))
    pygame.draw.ellipse(sprite, (202, 244, 248, 126),
                        pygame.Rect(center - 1, 3, 3, 7))
    _TRAIL_SPRITES[head_diameter] = sprite
    return sprite


def _clear_cache_for_tests() -> None:
    """Keep the bounded sprite cache observable without exposing it to app code."""
    _DROP_SPRITES.clear()
    _TRAIL_SPRITES.clear()


def draw(panel: pygame.Surface, frame: SceneFrame) -> None:
    """Paint sparse water lenses only for rain/thunder, after the scene itself."""
    code = frame.weather_code
    if code is None or (code not in RAIN_CODES and code not in THUNDER_CODES):
        return
    width, height = panel.get_size()
    if width <= 0 or height <= 0:
        return

    seed = frame.day_seed
    # Fixed count and cached sprites make this cheap enough for the 15–20fps
    # ambient loop.  The small side-to-side drift keeps static droplets alive.
    for index in range(30):
        diameter = _DROP_DIAMETERS[index % len(_DROP_DIAMETERS)]
        sprite = _drop_sprite(diameter)
        x = hash_unit(seed, index, 101) * (width + 40) - 20
        y = hash_unit(seed, index, 103) * (height + 32) - 16
        x += math.sin(frame.t * (0.10 + index % 3 * 0.02) + index) * 1.2
        panel.blit(sprite, (round(x - sprite.get_width() / 2),
                            round(y - sprite.get_height() / 2)))

    for index in range(7):
        diameter = _DROP_DIAMETERS[(index + 1) % len(_DROP_DIAMETERS)]
        speed = 8.5 + hash_unit(seed, index, 201) * 10.0
        x = hash_unit(seed, index, 203) * width
        head_y = (hash_unit(seed, index, 205) * (height + 88) + frame.t * speed) % (height + 88) - 24
        trail = _trail_sprite(diameter)
        # The tail sits behind the head and fades continuously upward.
        panel.blit(trail, (round(x - trail.get_width() / 2), round(head_y - trail.get_height() + diameter * 0.35)))
        head = _drop_sprite(diameter)
        panel.blit(head, (round(x - head.get_width() / 2), round(head_y - head.get_height() / 2)))
