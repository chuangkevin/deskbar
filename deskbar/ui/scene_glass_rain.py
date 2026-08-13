"""Rain on the central scene's glass, with bounded local refraction.

Most drops are tiny beads pinned by surface tension.  Only a few sufficiently
large drops overcome that pinning, accelerate towards terminal velocity and
leave a short, faint wet path.  Runtime work is deliberately local: no
panel-sized alpha surface and at most five small refraction patches per frame.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_common import hash_unit
from deskbar.ui.scene_runtime import SceneFrame
from deskbar.ui.weatherfx import RAIN_CODES, THUNDER_CODES


_ASSET_PATH: Final = (
    Path(__file__).resolve().parent.parent / "assets" / "weatherfx" / "drop.png"
)
_DRIZZLE_CODES: Final = set(range(51, 58))
_HEAVY_CODES: Final = {63, 65, 66, 67, 81, 82} | THUNDER_CODES

# (inner width, inner height, horizontal flip, rotation).  The source image is
# soft and asymmetric, so scale/flip/angle create genuinely different contact
# shapes without an unbounded runtime cache.
_FIXED_KEYS: Final = (
    (3, 4, False, -5), (4, 5, True, 4), (5, 6, False, 2),
    (5, 7, True, -3), (6, 7, False, 6), (6, 8, True, 1),
    (7, 8, False, -4), (8, 10, True, 5), (9, 11, False, 0),
    (10, 12, True, -5), (12, 15, False, 4), (14, 18, True, -2),
)
_SLIDING_KEYS: Final = (
    (10, 16, False, -7), (14, 18, True, 6), (13, 22, False, -3),
    (19, 24, True, 7), (20, 31, False, -5),
)
_ALL_KEYS: Final = _FIXED_KEYS + _SLIDING_KEYS

_DROP_SPRITE_CACHE: dict[tuple[int, int, bool, int], pygame.Surface] = {}
_ALPHA_MASK_CACHE: dict[tuple[int, int, bool, int], pygame.Surface] = {}
_RAW_DROP: pygame.Surface | None = None
_MAX_CACHE_SIZE: Final = len(_ALL_KEYS)

_MAX_TRAIL_LENGTH: Final = 42.0
_MAX_TRAIL_ALPHA: Final = 34


def _raw_drop() -> pygame.Surface:
    global _RAW_DROP
    if _RAW_DROP is None:
        _RAW_DROP = pygame.image.load(str(_ASSET_PATH))
    return _RAW_DROP


def _drop_sprite(key: tuple[int, int, bool, int]) -> pygame.Surface:
    """Return one baked, transparent lens variant from a finite key space."""
    cached = _DROP_SPRITE_CACHE.get(key)
    if cached is not None:
        return cached
    if key not in _ALL_KEYS:
        raise KeyError(f"unknown glass-drop variant: {key}")
    width, height, flip_x, angle = key
    lens = pygame.transform.smoothscale(_raw_drop(), (width, height))
    if flip_x:
        lens = pygame.transform.flip(lens, True, False)
    if angle:
        lens = pygame.transform.rotate(lens, angle)
    # Explicit transparent guard band prevents scaled edge texels reading as a
    # rectangular card on dark scenes.
    sprite = pygame.Surface(
        (lens.get_width() + 4, lens.get_height() + 4), pygame.SRCALPHA
    )
    sprite.blit(lens, (2, 2))
    _DROP_SPRITE_CACHE[key] = sprite
    return sprite


def _alpha_mask(key: tuple[int, int, bool, int]) -> pygame.Surface:
    """White RGB plus the source lens alpha, suitable for RGBA multiplication."""
    cached = _ALPHA_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    mask = _drop_sprite(key).copy()
    mask.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)
    _ALPHA_MASK_CACHE[key] = mask
    return mask


def _clear_cache_for_tests() -> None:
    global _RAW_DROP
    _DROP_SPRITE_CACHE.clear()
    _ALPHA_MASK_CACHE.clear()
    _RAW_DROP = None


def _population(code: int) -> tuple[int, int, float]:
    """Return (pinned beads, sliding drops, terminal-speed multiplier)."""
    if code in _DRIZZLE_CODES:
        return 34, 1, 0.72
    if code in _HEAVY_CODES:
        return 70, 5, 1.22
    return 50, 3, 1.0


def _fixed_key(seed: int, index: int) -> tuple[int, int, bool, int]:
    """Strongly favour 3–9px beads; larger pinned drops stay exceptional."""
    pick = hash_unit(seed, index, 101)
    if pick < 0.90:
        pool = _FIXED_KEYS[:9]
        local = hash_unit(seed, index, 102)
        return pool[min(len(pool) - 1, int(local ** 1.55 * len(pool)))]
    pool = _FIXED_KEYS[9:]
    return pool[min(len(pool) - 1, int(hash_unit(seed, index, 103) * len(pool)))]


def _terminal_velocity(
    key: tuple[int, int, bool, int], speed_factor: float, seed: int, index: int
) -> float:
    width = key[0]
    variation = 0.88 + hash_unit(seed, index, 211) * 0.24
    return (22.0 + width * 1.85) * speed_factor * variation


def _path_x(seed: int, index: int, y: float, start_y: float, x_base: float) -> float:
    """A low-frequency, individual rivulet path anchored at its birth point."""
    amplitude = 2.0 + hash_unit(seed, index, 221) * 5.0
    frequency = 0.015 + hash_unit(seed, index, 223) * 0.014
    phase = hash_unit(seed, index, 227) * math.tau
    distance = y - start_y
    primary = math.sin(distance * frequency + phase) - math.sin(phase)
    secondary = math.sin(distance * frequency * 0.43 + phase * 1.7) \
        - math.sin(phase * 1.7)
    return x_base + amplitude * (primary * 0.72 + secondary * 0.28)


def _sliding_state(
    frame_t: float,
    seed: int,
    index: int,
    key: tuple[int, int, bool, int],
    speed_factor: float,
    panel_width: int,
    panel_height: int,
) -> tuple[float, float, float, bool, float]:
    """Return x, y, start_y, moving, travelled using stick→terminal physics."""
    start_y = 18.0 + hash_unit(seed, index, 231) * panel_height * 0.48
    x_base = 18.0 + hash_unit(seed, index, 233) * max(1.0, panel_width - 36.0)
    velocity = _terminal_velocity(key, speed_factor, seed, index)
    tau = 0.72 + hash_unit(seed, index, 239) * 0.62
    travel_distance = panel_height + 46.0 - start_y
    travel_seconds = travel_distance / velocity + tau
    pin_fraction = 0.12 + hash_unit(seed, index, 241) * 0.23
    cycle_seconds = travel_seconds / (1.0 - pin_fraction)
    pin_seconds = cycle_seconds - travel_seconds
    phase = hash_unit(seed, index, 251) * cycle_seconds
    local_t = (frame_t + phase) % cycle_seconds
    if local_t < pin_seconds:
        return x_base, start_y, start_y, False, 0.0
    moving_t = local_t - pin_seconds
    # v(t)=v_terminal*(1-exp(-t/tau)); its integral is continuous and monotonic.
    travelled = velocity * (
        moving_t - tau * (1.0 - math.exp(-moving_t / tau))
    )
    y = start_y + travelled
    x = _path_x(seed, index, y, start_y, x_base)
    return x, y, start_y, True, travelled


def _draw_wet_trail(
    panel: pygame.Surface,
    seed: int,
    index: int,
    head_x: float,
    head_y: float,
    start_y: float,
    travelled: float,
) -> None:
    """Blend a short neutral wet path behind the head on a tiny alpha surface."""
    trail_length = min(_MAX_TRAIL_LENGTH, max(0.0, travelled * 0.20))
    if trail_length < 4.0:
        return
    x_base = head_x - (
        _path_x(seed, index, head_y, start_y, 0.0)
    )
    top_y = head_y - trail_length
    samples: list[tuple[float, float]] = []
    steps = max(3, round(trail_length / 3.0))
    for step in range(steps + 1):
        amount = step / steps
        y = top_y + trail_length * amount
        samples.append((_path_x(seed, index, y, start_y, x_base), y))
    min_x = math.floor(min(point[0] for point in samples)) - 3
    max_x = math.ceil(max(point[0] for point in samples)) + 3
    min_y = math.floor(top_y) - 2
    max_y = math.ceil(head_y) + 2
    trail = pygame.Surface((max_x - min_x + 1, max_y - min_y + 1), pygame.SRCALPHA)
    local = [(round(x - min_x), round(y - min_y)) for x, y in samples]
    pygame.draw.lines(trail, (164, 180, 190, 10), False, local, 3)
    pygame.draw.aalines(
        trail, (202, 216, 222, _MAX_TRAIL_ALPHA), False, local
    )
    panel.blit(trail, (min_x, min_y))


def _draw_refracted_drop(
    panel: pygame.Surface,
    key: tuple[int, int, bool, int],
    center_x: float,
    center_y: float,
    rim_alpha: int,
) -> None:
    """Magnify/offset the actual scene inside a lens, then add a faint baked rim."""
    sprite = _drop_sprite(key)
    width, height = sprite.get_size()
    left = round(center_x - width / 2)
    top = round(center_y - height / 2)
    rect = pygame.Rect(left, top, width, height)
    if not panel.get_rect().contains(rect):
        rim = sprite.copy()
        rim.set_alpha(rim_alpha)
        panel.blit(rim, (left, top))
        return
    background = panel.subsurface(rect).copy()
    scaled = pygame.transform.smoothscale(
        background, (width + 4, height + 4)
    )
    refracted = scaled.subsurface(pygame.Rect(3, 1, width, height)).copy()
    refracted.blit(_alpha_mask(key), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    panel.blit(refracted, (left, top))
    rim = sprite.copy()
    rim.set_alpha(rim_alpha)
    panel.blit(rim, (left, top))


def draw(panel: pygame.Surface, frame: SceneFrame) -> None:
    """Draw rain lenses only when the real weather is rain or thunder."""
    code = frame.weather_code
    if code is None or (code not in RAIN_CODES and code not in THUNDER_CODES):
        return
    width, height = panel.get_size()
    if width <= 0 or height <= 0:
        return
    seed = frame.day_seed
    fixed_count, sliding_count, speed_factor = _population(code)

    for index in range(fixed_count):
        key = _fixed_key(seed, index)
        sprite = _drop_sprite(key)
        x = hash_unit(seed, index, 271) * (width + 12) - 6
        y = hash_unit(seed, index, 277) * (height + 12) - 6
        # Pinned means pinned: only sub-pixel contact-angle breathing, not drift.
        x += math.sin(frame.t * 0.31 + index * 1.7) * 0.18
        y += math.cos(frame.t * 0.27 + index * 1.3) * 0.12
        sprite.set_alpha(36 + round(hash_unit(seed, index, 281) * 34))
        panel.blit(
            sprite,
            (round(x - sprite.get_width() / 2), round(y - sprite.get_height() / 2)),
        )

    for local_index in range(sliding_count):
        index = 100 + local_index
        pick = hash_unit(seed, index, 283)
        key = _SLIDING_KEYS[min(len(_SLIDING_KEYS) - 1, int(pick * len(_SLIDING_KEYS)))]
        x, y, start_y, moving, travelled = _sliding_state(
            frame.t, seed, index, key, speed_factor, width, height
        )
        if moving:
            _draw_wet_trail(panel, seed, index, x, y, start_y, travelled)
        rim_alpha = 42 + round(hash_unit(seed, index, 293) * 24)
        _draw_refracted_drop(panel, key, x, y, rim_alpha)
