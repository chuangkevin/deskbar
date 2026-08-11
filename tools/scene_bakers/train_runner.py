"""Bake original cinematic pixel-train and pixel-runner worlds."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Final

import numpy as np
import pygame


LOW_SIZE: Final = (620, 236)
OUTPUT_SIZE: Final = (1240, 472)
TRAIN_SKIES: Final = {
    "night": ((5, 12, 31), (50, 61, 83)),
    "dawn": ((38, 28, 54), (191, 103, 87)),
    "day": ((48, 109, 158), (176, 199, 198)),
}
RUNNER_SKIES: Final = {
    "night": ((8, 13, 35), (67, 56, 79)),
    "dawn": ((55, 35, 61), (213, 124, 87)),
    "day": ((50, 120, 171), (189, 204, 179)),
}


def _save(
    path: Path,
    source: pygame.Surface,
    transparent: bool,
    smooth: bool = False,
) -> None:
    """Scale artwork while enforcing opaque-base and transparent-edge contracts."""
    prepared = source.copy()
    alpha = pygame.surfarray.pixels_alpha(prepared)
    if transparent:
        alpha[0, :] = alpha[-1, :] = 0
        alpha[:, 0] = alpha[:, -1] = 0
    else:
        alpha[:, :] = 255
    del alpha
    transform = pygame.transform.smoothscale if smooth else pygame.transform.scale
    output = transform(prepared, OUTPUT_SIZE)
    output_alpha = pygame.surfarray.pixels_alpha(output)
    if transparent:
        output_alpha[0, :] = output_alpha[-1, :] = 0
        output_alpha[:, 0] = output_alpha[:, -1] = 0
    else:
        output_alpha[:, :] = 255
    del output_alpha
    pygame.image.save(output, path)


def _textured_disc(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    seed: int,
) -> None:
    """Paint a dithered moon/sun with a broken pixel edge and surface relief."""
    width, height = LOW_SIZE
    y, x = np.mgrid[0:height, 0:width]
    dx = x - center[0]
    dy = y - center[1]
    distance = np.sqrt(dx * dx + dy * dy)
    generator = np.random.default_rng(seed)
    relief = (
        np.sin(x * 0.63 + seed) * 2.2
        + np.sin(y * 0.51 - seed) * 1.8
        + generator.integers(-2, 3, (height, width))
    )
    mask = distance <= radius + relief * 0.18
    radial = np.clip(distance / radius, 0.0, 1.0)
    shade = relief - radial * 10.0
    base = np.asarray(color, dtype=np.float32)
    rgb = np.clip(base[None, None, :] + shade[..., None], 0, 255).astype(np.uint8)
    pixels = pygame.surfarray.pixels3d(surface)
    pixels[mask.T] = rgb.swapaxes(0, 1)[mask.T]
    del pixels


def _sky_train(
    name: str,
    colors: tuple[tuple[int, int, int], tuple[int, int, int]],
    seed: int,
) -> pygame.Surface:
    """Build a rich, atmospheric, non-uniform sky with organic cloud grain and celestial detail."""
    width, height = LOW_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)

    # Curved non-uniform vertical gradient
    amount = np.clip((y / (height * 0.88)) ** 1.25, 0.0, 1.0)[..., None]
    top = np.asarray(colors[0], dtype=np.float32)
    bottom = np.asarray(colors[1], dtype=np.float32)
    rgb = top + (bottom - top) * amount

    # Multi-frequency organic cloud grain
    cloud = (
        np.sin(x * 0.016 + np.sin(y * 0.042) * 1.8 + seed) * 0.52
        + np.sin(x * 0.039 - y * 0.024 + seed * 0.35) * 0.32
        + np.sin(x * 0.008 + y * 0.018) * 0.16
    )
    cloud *= np.exp(-((y - height * 0.44) / (height * 0.25)) ** 2)

    tint = {
        "night": (12.0, 16.0, 30.0),
        "dawn": (36.0, 18.0, 24.0),
        "day": (16.0, 22.0, 26.0),
    }[name]
    rgb += cloud[..., None] * np.asarray(tint, dtype=np.float32)

    generator = np.random.default_rng(seed)
    dither = generator.integers(-2, 3, (height, width, 1))
    rgb = np.floor((rgb + dither) / 3.0) * 3.0

    surface = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    pygame.surfarray.blit_array(surface, np.swapaxes(np.clip(rgb, 0, 255).astype(np.uint8), 0, 1))

    if name == "night":
        # Stars with color temperature variation & soft diffraction
        for star in range(65):
            sx = (star * 103 + 29) % width
            sy = (star * 47 + 13) % 110
            shade = 130 + star % 5 * 22
            star_color = (
                shade,
                min(255, shade + 8 + (star % 3) * 6),
                min(255, shade + 22 + (star % 2) * 15),
                255,
            )
            surface.set_at((sx, sy), star_color)
            if star % 8 == 0:
                surface.set_at((sx + 1, sy), (shade // 2, shade // 2 + 10, shade // 2 + 25, 255))
        # Detailed textured moon with crescent shading and halo
        _draw_train_moon(surface, (485, 46), 16, seed + 101)
    elif name == "dawn":
        # Morning dawn sun veiled behind golden horizon haze
        _draw_train_sun(surface, (495, 78), 17, (248, 168, 105), seed + 201, is_dawn=True)
    elif name == "day":
        # Crisp daylight sun with multi-layered dithered corona halo
        _draw_train_sun(surface, (478, 44), 16, (254, 245, 185), seed + 301, is_dawn=False)

    alpha = pygame.surfarray.pixels_alpha(surface)
    alpha[:, :] = 255
    del alpha
    return surface


def _draw_train_moon(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    seed: int,
) -> None:
    """Paint a detailed lunar crescent/gibbous with crater relief and soft halo glow."""
    cx, cy = center
    width, height = LOW_SIZE
    generator = np.random.default_rng(seed)

    # Outer glow halo
    for r in range(radius + 10, radius, -1):
        alpha_val = int(25 * (1.0 - (r - radius) / 10.0))
        glow_surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (170, 195, 225, alpha_val), (r + 1, r + 1), r)
        surface.blit(glow_surf, (cx - r - 1, cy - r - 1))

    # Moon surface raster
    y_grid, x_grid = np.mgrid[0:height, 0:width]
    dx = x_grid - cx
    dy = y_grid - cy
    dist = np.sqrt(dx * dx + dy * dy)

    # Crater & maria relief
    relief = (
        np.sin(x_grid * 0.55 + seed) * 2.0
        + np.sin(y_grid * 0.48 - seed) * 1.6
        + generator.integers(-2, 3, (height, width))
    )
    # Moon disc mask with organic crater edge
    disc_mask = dist <= radius + relief * 0.15

    # Crescent shadow cutout (dark side of moon)
    shadow_dx = dx - (radius * 0.45)
    shadow_dist = np.sqrt(shadow_dx * shadow_dx + dy * dy)
    lit_mask = disc_mask & (shadow_dist >= radius * 0.72)

    base_color = np.array([215.0, 228.0, 238.0], dtype=np.float32)
    shade = relief * 4.0 - (dist / radius) * 12.0
    rgb = np.clip(base_color[None, None, :] + shade[..., None], 120, 255).astype(np.uint8)

    pixels = pygame.surfarray.pixels3d(surface)
    pixels[lit_mask.T] = rgb.swapaxes(0, 1)[lit_mask.T]
    del pixels


def _draw_train_sun(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    seed: int,
    is_dawn: bool,
) -> None:
    """Paint a warm sun with multi-layered dithered corona halo and textured limb."""
    cx, cy = center
    width, height = LOW_SIZE

    # Soft ambient corona halo
    halo_color = (255, 210, 140) if is_dawn else (252, 235, 175)
    for r in range(radius + 18, radius, -2):
        alpha_val = int(22 * (1.0 - (r - radius) / 18.0))
        glow_surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*halo_color, alpha_val), (r + 1, r + 1), r)
        surface.blit(glow_surf, (cx - r - 1, cy - r - 1))

    # Sun disc with dithered edge relief
    _textured_disc(surface, center, radius, color, seed)


def _periodic_y(x: int, base: float, first: float, second: float) -> int:
    angle = math.tau * (x - 1) / (LOW_SIZE[0] - 2)
    return round(base + math.sin(angle) * first + math.sin(angle * 3.0 + 0.8) * second)


def _wrapped_x(x: int, margin: int = 0) -> tuple[int, ...]:
    period = LOW_SIZE[0] - 2
    return tuple(
        candidate
        for candidate in (x - period, x, x + period)
        if -margin <= candidate < LOW_SIZE[0] + margin
    )


def _draw_train_horizon(surface: pygame.Surface) -> None:
    """Build seam-conscious distant mountain ridges, valley town settlement, and viaduct."""
    width, height = LOW_SIZE
    w_period = width - 2

    # 1. Distant Mountain Ridge 1 (Farther, atmospheric deep silhouette)
    poly_far = [(0, 160)]
    for x in range(width):
        ang = math.tau * (x - 1) / w_period
        y = 112 + round(
            math.sin(ang) * 15.0
            + math.sin(ang * 2.0 - 0.4) * 8.0
            + math.sin(ang * 3.0 + 1.1) * 4.0
        )
        poly_far.append((x, y))
    poly_far.extend([(width - 1, 160), (0, 160)])
    pygame.draw.polygon(surface, (45, 58, 76, 235), poly_far)

    # Subtle slope shading highlights on ridge 1
    for x in range(2, width - 2, 8):
        ang = math.tau * (x - 1) / w_period
        y1 = 112 + round(
            math.sin(ang) * 15.0
            + math.sin(ang * 2.0 - 0.4) * 8.0
            + math.sin(ang * 3.0 + 1.1) * 4.0
        )
        dy = round(math.cos(ang) * 15.0 + 2.0 * math.cos(ang * 2.0 - 0.4) * 8.0)
        if dy > 0:
            pygame.draw.line(surface, (58, 72, 92, 140), (x, y1), (x + 4, y1 + 10), 2)

    # 2. Distant Mountain Ridge 2 (Closer, richer silhouette)
    poly_mid_far = [(0, 160)]
    for x in range(width):
        ang = math.tau * (x - 1) / w_period
        y = 126 + round(
            math.cos(ang + 0.8) * 11.0
            + math.sin(ang * 2.0 + 1.5) * 6.0
            + math.sin(ang * 4.0) * 3.0
        )
        poly_mid_far.append((x, y))
    poly_mid_far.extend([(width - 1, 160), (0, 160)])
    pygame.draw.polygon(surface, (36, 48, 64, 245), poly_mid_far)

    # 3. Valley Town Settlement (Nestled in low mountain valleys)
    building_specs = (
        (42, 11, 14, "house"), (78, 14, 18, "spire"), (122, 10, 12, "house"),
        (165, 16, 20, "tower"), (215, 9, 11, "house"), (335, 12, 15, "house"),
        (382, 15, 22, "spire"), (438, 10, 13, "house"), (485, 14, 16, "tower"),
        (542, 11, 14, "house"), (588, 9, 11, "house")
    )
    for base_x, b_width, b_height, b_type in building_specs:
        for x in _wrapped_x(base_x, b_width):
            ang = math.tau * (x - 1) / w_period
            ground_y = 126 + round(
                math.cos(ang + 0.8) * 11.0
                + math.sin(ang * 2.0 + 1.5) * 6.0
                + math.sin(ang * 4.0) * 3.0
            )
            b_top = ground_y - b_height
            pygame.draw.rect(surface, (30, 40, 52, 250), (x, b_top, b_width, b_height))
            if b_type == "spire":
                pygame.draw.polygon(
                    surface,
                    (24, 32, 42, 255),
                    ((x - 2, b_top), (x + b_width // 2, b_top - 9), (x + b_width + 2, b_top)),
                )
            elif b_type == "tower":
                pygame.draw.rect(surface, (24, 32, 42, 255), (x - 1, b_top - 3, b_width + 2, 3))
            else:
                pygame.draw.polygon(
                    surface,
                    (24, 32, 42, 255),
                    ((x - 2, b_top), (x + b_width // 2, b_top - 5), (x + b_width + 2, b_top)),
                )
            pygame.draw.rect(surface, (255, 198, 92, 220), (x + 3, b_top + 4, 2, 3))
            if b_width > 12:
                pygame.draw.rect(surface, (255, 198, 92, 220), (x + 8, b_top + 4, 2, 3))

    # 4. Rail Viaduct Bridge in far valley
    for base_x in (265,):
        for vx in _wrapped_x(base_x, 50):
            pygame.draw.rect(surface, (32, 42, 54, 240), (vx, 142, 48, 12))
            for arch_x in range(vx + 4, vx + 44, 14):
                pygame.draw.ellipse(surface, (0, 0, 0, 0), (arch_x, 146, 10, 10))

    # 5. Low mist haze along horizon
    pygame.draw.rect(surface, (140, 165, 185, 45), (0, 150, width, 10))


def _draw_train_midground(surface: pygame.Surface) -> None:
    """Paint periodic rolling countryside hills, irregular trees, small station, and field mist."""
    width, height = LOW_SIZE
    w_period = width - 2

    # 1. Rolling Countryside Ground Profile
    poly_ground = [(0, height)]
    for x in range(width):
        ang = math.tau * (x - 1) / w_period
        y = 148 + round(
            math.sin(ang) * 7.0
            + math.sin(ang * 2.0 + 0.7) * 4.0
            + math.cos(ang * 3.0) * 2.0
        )
        poly_ground.append((x, y))
    poly_ground.extend([(width - 1, height), (0, height)])
    pygame.draw.polygon(surface, (48, 74, 55, 245), poly_ground)

    # Terraced field rows / crop lines along slopes
    for row in range(5):
        y_base = 156 + row * 6
        for x in range(0, width, 18):
            ang = math.tau * (x - 1) / w_period
            y_offset = round(math.sin(ang) * 4.0)
            pygame.draw.line(
                surface,
                (68, 98, 75, 160),
                (x, y_base + y_offset),
                (x + 12, y_base + y_offset + 3),
                1,
            )

    # 2. Irregular Vegetation & Trees (Varied species, canopy shapes, heights)
    tree_positions = [
        (18, "oak", 22), (45, "pine", 26), (82, "bush", 12), (115, "oak", 24),
        (148, "pine", 28), (192, "pine", 22), (240, "oak", 26), (285, "oak", 20),
        (325, "pine", 27), (368, "bush", 14), (405, "oak", 25), (452, "pine", 29),
        (495, "oak", 21), (538, "pine", 24), (575, "oak", 23), (602, "bush", 13)
    ]
    for base_x, species, t_height in tree_positions:
        for x in _wrapped_x(base_x, 20):
            ang = math.tau * (x - 1) / w_period
            ground_y = 148 + round(
                math.sin(ang) * 7.0
                + math.sin(ang * 2.0 + 0.7) * 4.0
                + math.cos(ang * 3.0) * 2.0
            )
            crown_y = ground_y - t_height

            # Trunk
            pygame.draw.rect(surface, (42, 32, 26, 240), (x - 1, crown_y + 8, 3, t_height - 6))

            if species == "pine":
                for tier, (t_w, t_h, y_off) in enumerate(((14, 8, 0), (18, 10, 6), (22, 12, 13))):
                    top_y = crown_y + y_off
                    pygame.draw.polygon(
                        surface,
                        (34 + tier * 4, 62 + tier * 6, 44 + tier * 3, 235),
                        ((x, top_y), (x - t_w // 2, top_y + t_h), (x + t_w // 2, top_y + t_h)),
                    )
                    pygame.draw.line(surface, (65, 105, 75, 200), (x, top_y), (x - 2, top_y + t_h - 2), 1)
            elif species == "oak":
                rad = t_height // 2
                pygame.draw.circle(surface, (36, 56, 42, 235), (x - 3, crown_y + rad), rad - 1)
                pygame.draw.circle(surface, (36, 56, 42, 235), (x + 4, crown_y + rad + 2), rad - 2)
                pygame.draw.circle(surface, (48, 78, 54, 240), (x, crown_y + rad - 2), rad)
                pygame.draw.circle(surface, (68, 104, 72, 220), (x - 2, crown_y + rad - 4), rad - 3)
            else:
                pygame.draw.ellipse(surface, (44, 68, 48, 230), (x - 7, ground_y - t_height, 14, t_height))

    # 3. Small Rural Train Station & Farmhouse
    for base_x in (210,):
        for sx in _wrapped_x(base_x, 35):
            ang = math.tau * (sx - 1) / w_period
            ground_y = 148 + round(
                math.sin(ang) * 7.0
                + math.sin(ang * 2.0 + 0.7) * 4.0
                + math.cos(ang * 3.0) * 2.0
            )
            pygame.draw.rect(surface, (54, 44, 36, 245), (sx - 5, ground_y - 4, 38, 5))
            h_top = ground_y - 20
            pygame.draw.rect(surface, (46, 38, 32, 250), (sx, h_top, 22, 16))
            pygame.draw.polygon(
                surface,
                (35, 28, 24, 255),
                ((sx - 3, h_top), (sx + 11, h_top - 7), (sx + 25, h_top)),
            )
            pygame.draw.rect(surface, (255, 208, 105, 240), (sx + 4, h_top + 4, 5, 5))
            pygame.draw.rect(surface, (28, 28, 28, 255), (sx + 30, ground_y - 18, 2, 14))
            pygame.draw.circle(surface, (255, 225, 140, 230), (sx + 31, ground_y - 18), 3)

    for base_x in (440,):
        for fx in _wrapped_x(base_x, 25):
            ang = math.tau * (fx - 1) / w_period
            ground_y = 148 + round(
                math.sin(ang) * 7.0
                + math.sin(ang * 2.0 + 0.7) * 4.0
                + math.cos(ang * 3.0) * 2.0
            )
            f_top = ground_y - 16
            pygame.draw.rect(surface, (42, 34, 28, 250), (fx, f_top, 18, 13))
            pygame.draw.polygon(
                surface,
                (32, 24, 20, 255),
                ((fx - 2, f_top), (fx + 9, f_top - 6), (fx + 20, f_top)),
            )
            pygame.draw.rect(surface, (255, 195, 85, 220), (fx + 3, f_top + 3, 4, 4))
            for post_x in range(fx + 22, fx + 42, 5):
                pygame.draw.rect(surface, (50, 40, 32, 220), (post_x, ground_y - 7, 1, 7))
            pygame.draw.line(surface, (50, 40, 32, 180), (fx + 20, ground_y - 5), (fx + 42, ground_y - 5), 1)

    # 4. Translucent Low Valley Mist / Haze Strip
    pygame.draw.rect(surface, (165, 190, 200, 50), (0, 168, width, 12))


def _draw_rail_signal(surface: pygame.Surface, x: int) -> None:
    """Draw detailed railway signal gantry post with active signal lamps."""
    mast = (24, 28, 33, 255)
    pygame.draw.rect(surface, mast, (x, 76, 4, 118))
    pygame.draw.rect(surface, (91, 91, 80, 255), (x + 1, 81, 1, 105))
    pygame.draw.rect(surface, mast, (x - 8, 69, 19, 33))
    pygame.draw.rect(surface, (10, 14, 18, 255), (x - 5, 72, 13, 27))
    pygame.draw.rect(surface, (235, 65, 45, 255), (x - 2, 74, 6, 6))
    pygame.draw.rect(surface, (245, 180, 50, 255), (x - 2, 83, 6, 6))
    pygame.draw.rect(surface, (55, 210, 110, 255), (x - 2, 92, 6, 4))
    pygame.draw.rect(surface, (213, 203, 156, 255), (x - 6, 111, 15, 8))
    pygame.draw.rect(surface, (48, 53, 53, 255), (x - 3, 113, 9, 2))
    pygame.draw.polygon(surface, mast, ((x - 7, 194), (x + 11, 194), (x + 7, 187), (x - 3, 187)))


def _draw_train_foreground(surface: pygame.Surface) -> None:
    """Create a fast adjacent track bed with sleepers, dual steel rails, signals, and catenary poles."""
    width, height = LOW_SIZE

    # 1. Ballast Gravel Bed Base
    pygame.draw.rect(surface, (36, 40, 44, 245), (0, 174, width, height - 174))
    for y, color in (
        (180, (52, 56, 60, 235)),
        (192, (44, 48, 52, 245)),
        (208, (34, 38, 42, 255)),
        (224, (26, 30, 34, 255)),
    ):
        pygame.draw.rect(surface, color, (0, y, width, height - y))

    # Dithered gravel stone texture
    for index in range(140):
        gx = (index * 73 + 19) % width
        gy = 178 + (index * 37 + 11) % 55
        stone_color = (68 + index % 4 * 12, 74 + index % 3 * 10, 80, 220) if index % 2 else (24, 28, 32, 220)
        surface.set_at((gx, gy), stone_color)

    # 2. Wooden Sleepers / Ties (Regular spacing every 16px)
    for index in range(40):
        sx = round(index * (width - 2) / 39)
        pygame.draw.polygon(
            surface,
            (62 + index % 3 * 4, 48 + index % 2 * 5, 38, 255),
            ((sx - 7, 202), (sx - 1, 198), (sx + 13, 232), (sx + 5, 234)),
        )
        pygame.draw.rect(surface, (82, 88, 94, 255), (sx - 3, 203, 3, 2))
        pygame.draw.rect(surface, (82, 88, 94, 255), (sx + 7, 226, 3, 2))

    # 3. Dual Continuous Parallel Steel Rails
    pygame.draw.rect(surface, (22, 26, 30, 255), (0, 223, width, 6))
    pygame.draw.rect(surface, (188, 198, 208, 255), (0, 222, width, 2))
    pygame.draw.rect(surface, (115, 122, 128, 255), (0, 224, width, 1))

    pygame.draw.rect(surface, (26, 30, 34, 255), (0, 203, width, 5))
    pygame.draw.rect(surface, (175, 185, 195, 255), (0, 202, width, 2))
    pygame.draw.rect(surface, (102, 108, 114, 255), (0, 204, width, 1))

    pygame.draw.line(surface, (78, 84, 88, 230), (0, 174), (width, 174), 2)

    # 4. Trackside Signal Mast
    for base_x in (145,):
        for candidate in _wrapped_x(base_x, 14):
            _draw_rail_signal(surface, candidate)

    # 5. Catenary / Telegraph Poles & Overhead Wires
    for base_x in (60, 290, 520):
        for px in _wrapped_x(base_x, 10):
            pygame.draw.rect(surface, (38, 44, 48, 255), (px, 138, 4, 38))
            pygame.draw.rect(surface, (48, 54, 58, 255), (px - 8, 142, 20, 3))
            pygame.draw.rect(surface, (230, 235, 240, 255), (px - 7, 139, 2, 3))
            pygame.draw.rect(surface, (230, 235, 240, 255), (px + 9, 139, 2, 3))

    pygame.draw.line(surface, (88, 96, 102, 180), (0, 139), (width, 139), 1)
    pygame.draw.line(surface, (88, 96, 102, 180), (0, 140), (width, 140), 1)

    # 6. Milestone Speed / Kilometer Post
    for candidate in _wrapped_x(380, 15):
        pygame.draw.rect(surface, (36, 42, 44, 255), (candidate, 152, 4, 42))
        pygame.draw.polygon(
            surface,
            (225, 218, 185, 255),
            ((candidate - 8, 152), (candidate + 12, 152), (candidate + 2, 136)),
        )
        pygame.draw.polygon(
            surface,
            (50, 56, 54, 255),
            ((candidate - 4, 150), (candidate + 8, 150), (candidate + 2, 139)),
        )


def _draw_window_reflection(surface: pygame.Surface) -> None:
    """Frame the landscape from inside a carriage with dark frame, glass glare, and fine water droplets."""
    width, height = LOW_SIZE
    frame = (8, 12, 18, 240)
    gasket = (21, 28, 34, 245)

    pygame.draw.rect(surface, frame, (0, 0, width, 12))
    pygame.draw.rect(surface, (32, 38, 43, 245), (0, 8, width, 5))
    pygame.draw.rect(surface, frame, (0, height - 19, width, 19))
    pygame.draw.rect(surface, (43, 45, 43, 250), (0, height - 20, width, 5))

    pygame.draw.rect(surface, gasket, (31, 0, 11, height))
    pygame.draw.rect(surface, (8, 11, 16, 255), (34, 0, 6, height))
    pygame.draw.rect(surface, (55, 57, 55, 180), (41, 12, 2, height - 31))
    pygame.draw.rect(surface, gasket, (577, 0, 12, height))
    pygame.draw.rect(surface, (8, 11, 16, 255), (579, 0, 6, height))
    pygame.draw.rect(surface, (55, 57, 55, 180), (575, 12, 2, height - 31))

    pygame.draw.polygon(
        surface,
        (17, 20, 25, 60),
        ((84, height - 20), (91, 190), (110, 180), (128, 191), (136, height - 20)),
    )
    pygame.draw.rect(surface, (119, 74, 48, 40), (77, 208, 68, 9))

    pygame.draw.rect(surface, (225, 199, 145, 42), (83, 21, 126, 4))
    pygame.draw.rect(surface, (243, 222, 176, 22), (88, 26, 116, 2))
    pygame.draw.rect(surface, (192, 150, 91, 30), (437, 31, 78, 3))
    pygame.draw.rect(surface, (230, 199, 139, 32), (447, 37, 58, 2))
    pygame.draw.polygon(
        surface,
        (204, 224, 226, 18),
        ((118, 12), (132, 12), (238, height - 20), (212, height - 20)),
    )
    pygame.draw.polygon(
        surface,
        (234, 211, 164, 15),
        ((356, 12), (363, 12), (438, height - 20), (425, height - 20)),
    )

    for drop in range(28):
        dx = 45 + (drop * 19 + 11) % (width - 90)
        dy = 16 + (drop * 13 + 7) % (height - 45)
        d_len = 2 + drop % 4
        for step in range(d_len):
            surface.set_at((dx, dy + step), (220, 240, 255, 95))
        surface.set_at((dx + 1, dy + d_len - 1), (15, 25, 35, 75))


def generate_train_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for index, (name, colors) in enumerate(TRAIN_SKIES.items()):
        base = _sky_train(name, colors, 100 + index)
        _save(out / f"train_base_{name}.png", base, False, smooth=True)

    far = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_train_horizon(far)
    _save(out / "train_far.png", far, True, smooth=True)

    mid = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_train_midground(mid)
    _save(out / "train_mid.png", mid, True, smooth=True)

    near = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_train_foreground(near)
    _save(out / "train_near.png", near, True, smooth=True)

    reflection = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_window_reflection(reflection)
    _save(out / "train_window_reflection.png", reflection, True, smooth=True)


RUNNER_SKIES: Final = {
    "night": ((10, 14, 38), (34, 48, 86)),
    "dawn": ((52, 28, 64), (220, 110, 68)),
    "day": ((44, 116, 182), (168, 210, 214)),
}


def _draw_runner_sky(
    name: str,
    colors: tuple[tuple[int, int, int], tuple[int, int, int]],
    seed: int,
) -> pygame.Surface:
    """Build a rich, textured, non-uniform quantized sky for valley runner."""
    width, height = LOW_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)

    # Curved vertical gradient for non-uniform aerial perspective
    amount = np.clip((y / (height * 0.82)) ** 1.35, 0.0, 1.0)[..., None]
    top = np.asarray(colors[0], dtype=np.float32)
    bottom = np.asarray(colors[1], dtype=np.float32)
    rgb = top + (bottom - top) * amount

    # Quantized cloud formations
    cloud = (
        np.sin(x * 0.015 + np.sin(y * 0.04) * 1.8 + seed) * 0.50
        + np.sin(x * 0.038 - y * 0.022 + seed * 0.4) * 0.32
        + np.sin(x * 0.008 + y * 0.016) * 0.18
    )
    cloud *= np.exp(-((y - height * 0.42) / (height * 0.24)) ** 2)

    cloud_tint = {
        "night": (14.0, 18.0, 32.0),
        "dawn": (35.0, 18.0, 22.0),
        "day": (18.0, 24.0, 28.0),
    }[name]
    rgb += cloud[..., None] * np.asarray(cloud_tint, dtype=np.float32)

    generator = np.random.default_rng(seed)
    dither = generator.integers(-3, 4, (height, width, 1))
    rgb = np.floor((rgb + dither) / 4.0) * 4.0

    surface = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    pygame.surfarray.blit_array(surface, np.swapaxes(np.clip(rgb, 0, 255).astype(np.uint8), 0, 1))

    # Add celestial details
    if name == "night":
        # Stars
        for star in range(64):
            sx = (star * 97 + 19) % width
            sy = (star * 37 + 11) % 115
            shade = 140 + star % 5 * 22
            surface.set_at((sx, sy), (shade, shade + 10, min(255, shade + 35), 255))
            if star % 7 == 0:
                surface.set_at((sx + 1, sy), (shade - 30, shade - 20, shade, 255))
        # Moon
        _textured_disc(surface, (480, 50), 16, (215, 225, 240), seed + 10)
    elif name == "dawn":
        # Morning star / dawn sun halo
        _textured_disc(surface, (490, 85), 18, (245, 175, 110), seed + 20)
    elif name == "day":
        # Daytime sun disc
        _textured_disc(surface, (470, 44), 16, (252, 238, 170), seed + 30)

    # Base chasm background below y=190
    chasm_color = {
        "night": (14, 18, 30, 255),
        "dawn": (38, 22, 34, 255),
        "day": (28, 44, 40, 255),
    }[name]
    pygame.draw.rect(surface, chasm_color, (0, 186, width, height - 186))

    alpha = pygame.surfarray.pixels_alpha(surface)
    alpha[:, :] = 255
    del alpha
    return surface


def _draw_runner_far(surface: pygame.Surface) -> None:
    """Draw low-contrast distant mountains, cloud bands, and flying birds."""
    width, _height = LOW_SIZE
    # Distant mountain ridge 1
    poly1 = [(0, 190)]
    for x in range(0, width + 10, 20):
        y = 115 + round(math.sin(x * 0.012 + 0.5) * 18 + math.sin(x * 0.035) * 8)
        poly1.append((x, y))
    poly1.extend([(width, 190), (0, 190)])
    pygame.draw.polygon(surface, (42, 54, 76, 180), poly1)

    # Distant mountain ridge 2 (closer, slightly darker)
    poly2 = [(0, 190)]
    for x in range(0, width + 10, 15):
        y = 135 + round(math.cos(x * 0.018 + 1.2) * 14 + math.sin(x * 0.04) * 6)
        poly2.append((x, y))
    poly2.extend([(width, 190), (0, 190)])
    pygame.draw.polygon(surface, (34, 44, 64, 210), poly2)

    # Cloud bands / birds
    for bx, by in ((60, 50), (220, 75), (420, 40), (530, 65)):
        pygame.draw.ellipse(surface, (180, 195, 215, 70), (bx, by, 70, 8))
        pygame.draw.ellipse(surface, (200, 215, 230, 50), (bx + 15, by - 3, 40, 6))

    # Flying birds (v-shapes)
    bird_color = (25, 35, 50, 160)
    for bx, by in ((140, 65), (152, 60), (166, 68), (380, 55), (392, 51)):
        pygame.draw.lines(surface, bird_color, False, [(bx, by), (bx + 3, by - 2), (bx + 6, by)], 1)


def _draw_runner_mid(surface: pygame.Surface) -> None:
    """Draw irregular coniferous pine forest, rocky ridges, and light mist."""
    width, _height = LOW_SIZE
    # Rocky ridge base
    ridge = [(0, 190)]
    for x in range(0, width + 10, 10):
        y = 152 + round(math.sin(x * 0.025) * 10 + math.sin(x * 0.08) * 4)
        ridge.append((x, y))
    ridge.extend([(width, 190), (0, 190)])
    pygame.draw.polygon(surface, (46, 58, 62, 220), ridge)

    # Coniferous pine trees
    tree_xs = (12, 38, 65, 95, 130, 175, 210, 245, 285, 320, 360, 400, 445, 485, 525, 570, 605)
    for index, x in enumerate(tree_xs):
        tree_h = 24 + (index * 7) % 18
        tree_y = 190 - tree_h
        trunk_color = (36, 28, 24, 230)
        leaf_color1 = (28, 68, 52, 235)
        leaf_color2 = (44, 92, 68, 235)

        # Trunk
        pygame.draw.rect(surface, trunk_color, (x - 1, tree_y + tree_h - 8, 3, 8))
        # Pine tiers
        tiers = 3
        for t in range(tiers):
            ty = tree_y + t * (tree_h // 3)
            tw = 6 + t * 5
            c = leaf_color2 if t % 2 == 0 else leaf_color1
            pygame.draw.polygon(
                surface, c,
                [(x, ty), (x - tw, ty + (tree_h // 3) + 2), (x + tw, ty + (tree_h // 3) + 2)]
            )

    # Mist band
    pygame.draw.rect(surface, (160, 180, 195, 45), (0, 178, width, 12))


def _draw_runner_near(surface: pygame.Surface) -> None:
    """Draw mossy stone and grass covered repeatable ground (y=190..236)."""
    width, height = LOW_SIZE
    ground_y = 190

    # Base ground rock fill
    pygame.draw.rect(surface, (44, 38, 34, 255), (0, ground_y, width, height - ground_y))

    # Layered stone strata
    for y in range(ground_y + 4, height, 6):
        row = (y - ground_y) // 6
        color = (52 + (row * 3) % 12, 46 + (row * 4) % 10, 40 + (row * 2) % 8, 255)
        pygame.draw.rect(surface, color, (0, y, width, 5))
        # Stone block dividers
        for x in range((row * 17) % 32, width, 32):
            pygame.draw.line(surface, (28, 24, 22, 255), (x, y), (x, y + 5), 1)

    # Mossy grass top layer (y=190..194)
    pygame.draw.rect(surface, (48, 118, 54, 255), (0, ground_y, width, 4))
    pygame.draw.rect(surface, (76, 168, 72, 255), (0, ground_y, width, 2))

    # Grass blades and moss tufts
    for x in range(0, width):
        if (x * 13 + 5) % 7 < 3:
            h = 2 + (x * 11) % 4
            pygame.draw.line(surface, (88, 186, 78, 255), (x, ground_y), (x, ground_y - h), 1)
        if (x * 17) % 19 == 0:
            pygame.draw.rect(surface, (36, 92, 44, 255), (x, ground_y + 3, 3, 3))


def _draw_messenger_pose(surface: pygame.Surface, origin: tuple[int, int], step: int) -> None:
    """Draw original hooded messenger character at origin (2x2 pixel blocks)."""
    ox, oy = origin
    pose_0 = (
        ".....HHHHHH.....",
        "....HHHHHHHH....",
        "...HHHGGGGHHH...",
        "...HHHGGGGHHH...",
        "....HHHHHHHH....",
        ".....CCCCCC.....",
        "CCCCCCCYYCCCCCC.",
        ".CCCCCCCYYC.TTT.",
        "..TTTTTTTTTTTTT.",
        "..TTTTBBTTTT....",
        "..TTTBBBBTTT....",
        "...LLLL..LL.....",
        "..LLLL....LL....",
        ".LLLL......LL...",
        ".DDDD......DDD..",
        "DDDDD.......DDDD",
        "................",
        "................",
    )
    pose_1 = (
        ".....HHHHHH.....",
        "....HHHHHHHH....",
        "...HHHGGGGHHH...",
        "...HHHGGGGHHH...",
        "....HHHHHHHH....",
        "....CCCCCC......",
        "CCCCCCCYYCCCC...",
        "..CCCCCCCYYCTT..",
        "..TTTTTTTTTTTT..",
        "..TTTTBBTTTT....",
        "..TTTBBBBTTT....",
        "....LL...LLLL...",
        "...LL.....LLLL..",
        "..LL.......LLLL.",
        "..DDD......DDDD.",
        "DDDD.......DDDDD",
        "................",
        "................",
    )
    palette = {
        "H": (24, 28, 52, 255),    # Hood/Cape (midnight indigo)
        "G": (96, 232, 220, 255),   # Glowing visor (cyan)
        "C": (228, 76, 88, 255),   # Scarf (crimson)
        "Y": (244, 196, 72, 255),   # Scarf trim (gold)
        "T": (56, 76, 104, 255),   # Tunic (steel blue)
        "B": (148, 92, 52, 255),   # Leather belt/bag
        "L": (36, 40, 56, 255),    # Pants/legs
        "D": (24, 26, 38, 255),    # Boots
    }
    grid = pose_1 if step else pose_0
    for row, line in enumerate(grid):
        for col, char in enumerate(line):
            if char in palette:
                pygame.draw.rect(
                    surface,
                    palette[char],
                    (ox + col * 2, oy + row * 2, 2, 2),
                )


def _draw_runner_obstacles_atlas(surface: pygame.Surface) -> None:
    """Draw original obstacles: mossy pillars, night beetle, stone & rune blocks."""
    # 1. Short Pillar at LOW_SIZE (105, 158, 28, 32)
    px, py, pw, ph = 105, 158, 28, 32
    pygame.draw.rect(surface, (54, 66, 78, 255), (px, py, pw, ph))
    pygame.draw.rect(surface, (72, 86, 100, 255), (px + 2, py + 2, pw - 4, ph - 4))
    pygame.draw.rect(surface, (38, 48, 58, 255), (px, py, pw, 4))  # Cap
    pygame.draw.rect(surface, (38, 48, 58, 255), (px, py + ph - 4, pw, 4))  # Base
    # Moss & carved glyph
    pygame.draw.rect(surface, (52, 124, 66, 255), (px + 2, py + 4, 6, 12))
    pygame.draw.rect(surface, (96, 212, 192, 255), (px + 12, py + 10, 4, 8))
    pygame.draw.rect(surface, (96, 212, 192, 255), (px + 10, py + 12, 8, 4))

    # 2. Tall Pillar at LOW_SIZE (324, 150, 28, 40)
    tpx, tpy, tpw, tph = 324, 150, 28, 40
    pygame.draw.rect(surface, (54, 66, 78, 255), (tpx, tpy, tpw, tph))
    pygame.draw.rect(surface, (72, 86, 100, 255), (tpx + 2, tpy + 2, tpw - 4, tph - 4))
    pygame.draw.rect(surface, (38, 48, 58, 255), (tpx, tpy, tpw, 4))  # Cap
    pygame.draw.rect(surface, (38, 48, 58, 255), (tpx, tpy + tph - 4, tpw, 4))  # Base
    # Vines & carved glyph
    pygame.draw.rect(surface, (44, 110, 58, 255), (tpx + 18, tpy + 6, 8, 20))
    pygame.draw.rect(surface, (96, 212, 192, 255), (tpx + 8, tpy + 14, 4, 12))

    # 3. Night Beetle at LOW_SIZE (184, 174, 16, 16)
    bx, by = 184, 174
    # Beetle body (16x16)
    pygame.draw.ellipse(surface, (32, 28, 48, 255), (bx + 1, by + 3, 14, 10))
    pygame.draw.ellipse(surface, (56, 48, 80, 255), (bx + 3, by + 4, 10, 8))
    # Glowing rune spot on carapace
    pygame.draw.circle(surface, (160, 88, 220, 255), (bx + 8, by + 7), 3)
    pygame.draw.circle(surface, (96, 232, 220, 255), (bx + 8, by + 7), 1)
    # Legs & eyes
    pygame.draw.line(surface, (20, 18, 30, 255), (bx + 3, by + 12), (bx + 1, by + 15), 1)
    pygame.draw.line(surface, (20, 18, 30, 255), (bx + 8, by + 12), (bx + 8, by + 15), 1)
    pygame.draw.line(surface, (20, 18, 30, 255), (bx + 13, by + 12), (bx + 15, by + 15), 1)
    pygame.draw.rect(surface, (96, 232, 220, 255), (bx + 2, by + 5, 2, 2))

    # 4. Inactive Stone Block ('brick') at LOW_SIZE (235, 142, 16, 16)
    k1x, k1y = 235, 142
    pygame.draw.rect(surface, (42, 50, 60, 255), (k1x, k1y, 16, 16))
    pygame.draw.rect(surface, (68, 80, 94, 255), (k1x + 1, k1y + 1, 14, 14))
    pygame.draw.rect(surface, (52, 62, 74, 255), (k1x + 3, k1y + 3, 10, 10))
    pygame.draw.rect(surface, (44, 100, 56, 255), (k1x + 1, k1y + 1, 4, 3))

    # 5. Glowing Rune Block ('question') at LOW_SIZE (251, 142, 16, 16)
    k2x, k2y = 251, 142
    pygame.draw.rect(surface, (42, 50, 60, 255), (k2x, k2y, 16, 16))
    pygame.draw.rect(surface, (68, 80, 94, 255), (k2x + 1, k2y + 1, 14, 14))
    # Glowing rune symbol
    pygame.draw.rect(surface, (244, 196, 72, 255), (k2x + 5, k2y + 4, 6, 2))
    pygame.draw.rect(surface, (244, 196, 72, 255), (k2x + 9, k2y + 6, 2, 4))
    pygame.draw.rect(surface, (96, 232, 220, 255), (k2x + 5, k2y + 9, 6, 2))
    pygame.draw.rect(surface, (96, 232, 220, 255), (k2x + 7, k2y + 12, 2, 2))


def generate_runner_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = LOW_SIZE

    for index, (name, colors) in enumerate(RUNNER_SKIES.items()):
        base = _draw_runner_sky(name, colors, 910 + index)
        _save(out / f"runner_base_{name}.png", base, False)

    far = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner_far(far)
    _save(out / "runner_far.png", far, True)

    mid = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner_mid(mid)
    _save(out / "runner_mid.png", mid, True)

    near = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner_near(near)
    _save(out / "runner_near.png", near, True)

    sheet = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_messenger_pose(sheet, (282, 106), 0)
    _draw_messenger_pose(sheet, (322, 106), 1)
    _save(out / "runner_sprite_sheet.png", sheet, True)

    obstacles = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner_obstacles_atlas(obstacles)
    _save(out / "runner_obstacles.png", obstacles, True)


def generate_train_runner_assets(out: Path) -> None:
    generate_train_assets(out)
    generate_runner_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scene", choices=("all", "train", "runner"), default="all")
    args = parser.parse_args()
    pygame.init()
    if args.scene in ("all", "train"):
        generate_train_assets(args.out)
    if args.scene in ("all", "runner"):
        generate_runner_assets(args.out)
    pygame.quit()


if __name__ == "__main__":
    main()
