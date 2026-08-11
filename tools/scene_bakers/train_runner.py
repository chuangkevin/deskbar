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


def _sky(
    colors: tuple[tuple[int, int, int], tuple[int, int, int]],
    seed: int,
) -> pygame.Surface:
    """Build a quantized sky with cloud grain instead of a uniform gradient."""
    width, height = LOW_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    amount = np.clip(y / (height * 0.86), 0.0, 1.0)[..., None]
    top = np.asarray(colors[0], dtype=np.float32)
    bottom = np.asarray(colors[1], dtype=np.float32)
    rgb = top + (bottom - top) * amount
    cloud = (
        np.sin(x * 0.018 + np.sin(y * 0.045) * 1.7 + seed) * 0.55
        + np.sin(x * 0.041 - y * 0.026 + seed * 0.37) * 0.30
        + np.sin(x * 0.009 + y * 0.019) * 0.15
    )
    cloud *= np.exp(-((y - height * 0.47) / (height * 0.26)) ** 2)
    rgb += cloud[..., None] * np.asarray((5.0, 6.0, 8.0), dtype=np.float32)
    generator = np.random.default_rng(seed)
    dither = generator.integers(-2, 3, (height, width, 1))
    rgb = np.floor((rgb + dither) / 3.0) * 3.0
    surface = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    pygame.surfarray.blit_array(surface, np.swapaxes(np.clip(rgb, 0, 255).astype(np.uint8), 0, 1))
    alpha = pygame.surfarray.pixels_alpha(surface)
    alpha[:, :] = 255
    del alpha
    return surface


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
    """Build a seam-conscious coast, settlement, and distant rail viaduct."""
    width, height = LOW_SIZE
    ridge = [(x, _periodic_y(x, 127.0, 7.0, 4.0)) for x in range(width)]
    pygame.draw.polygon(
        surface,
        (51, 66, 79, 218),
        [*ridge, (width - 1, 157), (0, 157)],
    )
    for index, x in enumerate((36, 73, 119, 168, 221, 279, 337, 395, 452, 511, 568)):
        ground = _periodic_y(x, 127.0, 7.0, 4.0)
        building_height = 8 + index * 7 % 18
        building_width = 13 + index % 3 * 4
        pygame.draw.rect(
            surface,
            (44 + index % 3 * 4, 55 + index % 2 * 5, 69, 238),
            (x, ground - building_height, building_width, building_height),
        )
        pygame.draw.polygon(
            surface,
            (35, 43, 55, 245),
            ((x - 2, ground - building_height),
             (x + building_width // 2, ground - building_height - 5),
             (x + building_width + 2, ground - building_height)),
        )
        if index % 2:
            pygame.draw.rect(
                surface,
                (190, 157, 89, 175),
                (x + 4, ground - building_height + 4, 2, 2),
            )

    pygame.draw.rect(surface, (35, 47, 58, 235), (0, 151, width, height - 151))
    pygame.draw.line(surface, (92, 111, 116, 165), (0, 153), (width, 153), 1)
    pygame.draw.line(surface, (29, 39, 48, 245), (0, 160), (width, 160), 3)
    for index in range(21):
        x = round(index * (width - 2) / 20)
        pygame.draw.rect(surface, (43, 53, 60, 235), (x, 157, 3, 12))
    for x in range(3, width, 47):
        pygame.draw.line(surface, (106, 128, 128, 90), (x, 176), (x + 21, 176), 1)


def _draw_train_midground(surface: pygame.Surface) -> None:
    """Paint periodic waterside fields and trackside vegetation."""
    width, height = LOW_SIZE
    bank = [(x, _periodic_y(x, 151.0, 4.0, 2.0)) for x in range(width)]
    pygame.draw.polygon(surface, (64, 86, 65, 242), [*bank, (width - 1, height), (0, height)])
    pygame.draw.polygon(
        surface,
        (54, 79, 73, 230),
        ((0, 169), (width, 165), (width, 193), (0, 198)),
    )
    pygame.draw.line(surface, (116, 135, 116, 135), (0, 174), (width, 170), 2)
    pygame.draw.line(surface, (38, 60, 57, 210), (0, 192), (width, 187), 2)
    pygame.draw.polygon(
        surface,
        (58, 77, 50, 245),
        ((0, 193), (width, 187), (width, height), (0, height)),
    )

    for index, x in enumerate((25, 68, 104, 151, 198, 243, 292, 341, 386, 433, 481, 526, 575)):
        crown_y = 145 + index * 5 % 10
        pygame.draw.rect(surface, (39, 58, 45, 225), (x, crown_y + 5, 3, 19))
        pygame.draw.polygon(
            surface,
            (55 + index % 3 * 5, 82 + index % 2 * 7, 54, 225),
            ((x + 1, crown_y - 7), (x - 8, crown_y + 8),
             (x - 3, crown_y + 7), (x - 11, crown_y + 16),
             (x + 12, crown_y + 16), (x + 5, crown_y + 7),
             (x + 10, crown_y + 8)),
        )
    for row, y in enumerate((199, 207, 218, 229)):
        pygame.draw.line(surface, (89 + row * 5, 98 + row * 4, 58, 210), (0, y), (width, y - 4), 2)
        for index in range(28):
            x = round(index * (width - 2) / 27) + row * 5
            pygame.draw.line(surface, (132, 128, 72, 135), (x, y - 5), (x + 11, y + 8), 1)


def _draw_rail_signal(surface: pygame.Surface, x: int) -> None:
    mast = (24, 28, 33, 255)
    pygame.draw.rect(surface, mast, (x, 76, 4, 118))
    pygame.draw.rect(surface, (91, 91, 80, 255), (x + 1, 81, 1, 105))
    pygame.draw.rect(surface, mast, (x - 8, 69, 19, 33))
    pygame.draw.rect(surface, (10, 14, 18, 255), (x - 5, 72, 13, 27))
    pygame.draw.rect(surface, (87, 49, 38, 255), (x - 2, 75, 6, 6))
    pygame.draw.rect(surface, (185, 139, 62, 255), (x - 2, 84, 6, 6))
    pygame.draw.rect(surface, (50, 91, 62, 255), (x - 2, 93, 6, 4))
    pygame.draw.rect(surface, (213, 203, 156, 255), (x - 6, 111, 15, 8))
    pygame.draw.rect(surface, (48, 53, 53, 255), (x - 3, 113, 9, 2))
    pygame.draw.polygon(surface, mast, ((x - 7, 194), (x + 11, 194), (x + 7, 187), (x - 3, 187)))


def _draw_train_foreground(surface: pygame.Surface) -> None:
    """Create a fast adjacent track with railway-specific signals and markers."""
    width, height = LOW_SIZE
    pygame.draw.rect(surface, (31, 37, 39, 238), (0, 181, width, height - 181))
    for y, color in ((187, (78, 78, 68, 215)), (195, (47, 54, 54, 245)),
                     (211, (64, 60, 52, 255)), (229, (38, 42, 43, 255))):
        pygame.draw.rect(surface, color, (0, y, width, height - y))
    for index in range(35):
        x = round(index * (width - 2) / 34)
        phase = index % 34
        pygame.draw.polygon(
            surface,
            (91 + phase % 3 * 5, 78 + phase % 2 * 6, 61, 255),
            ((x - 7, 202), (x - 1, 199), (x + 12, 232), (x + 4, 234)),
        )
    pygame.draw.rect(surface, (26, 31, 35, 255), (0, 202, width, 5))
    pygame.draw.rect(surface, (141, 135, 111, 255), (0, 202, width, 2))
    pygame.draw.rect(surface, (18, 23, 27, 255), (0, 222, width, 6))
    pygame.draw.rect(surface, (119, 113, 94, 255), (0, 222, width, 2))
    pygame.draw.rect(surface, (44, 50, 50, 245), (0, 172, width, 4))
    pygame.draw.line(surface, (112, 114, 99, 230), (0, 167), (width, 165), 2)
    for x in range(0, width + 1, 103):
        pygame.draw.rect(surface, (46, 52, 51, 245), (x, 164, 4, 22))
        pygame.draw.line(surface, (65, 70, 66, 220), (x + 2, 168), (x + 18, 180), 1)
    for x in (205,):
        for candidate in _wrapped_x(x, 14):
            _draw_rail_signal(surface, candidate)
    for candidate in _wrapped_x(506, 18):
        pygame.draw.rect(surface, (37, 43, 44, 255), (candidate, 145, 4, 50))
        pygame.draw.polygon(
            surface,
            (212, 194, 134, 255),
            ((candidate - 10, 145), (candidate + 14, 145), (candidate + 2, 128)),
        )
        pygame.draw.polygon(
            surface,
            (57, 62, 59, 255),
            ((candidate - 5, 142), (candidate + 9, 142), (candidate + 2, 132)),
        )


def _draw_window_reflection(surface: pygame.Surface) -> None:
    """Frame the landscape from inside a carriage with restrained glass glare."""
    width, height = LOW_SIZE
    frame = (8, 12, 18, 238)
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

    pygame.draw.rect(surface, (225, 199, 145, 48), (83, 21, 126, 4))
    pygame.draw.rect(surface, (243, 222, 176, 24), (88, 26, 116, 2))
    pygame.draw.rect(surface, (192, 150, 91, 32), (437, 31, 78, 3))
    pygame.draw.rect(surface, (230, 199, 139, 35), (447, 37, 58, 2))
    pygame.draw.polygon(
        surface,
        (204, 224, 226, 20),
        ((118, 12), (132, 12), (238, height - 20), (212, height - 20)),
    )
    pygame.draw.polygon(
        surface,
        (234, 211, 164, 16),
        ((356, 12), (363, 12), (438, height - 20), (425, height - 20)),
    )
    pygame.draw.polygon(
        surface,
        (17, 20, 25, 66),
        ((84, height - 20), (91, 190), (110, 180), (128, 191),
         (136, height - 20)),
    )
    pygame.draw.rect(surface, (119, 74, 48, 42), (77, 208, 68, 9))


def generate_train_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    discs = {
        "night": ((484, 48), (189, 205, 213), 701),
        "dawn": ((500, 91), (232, 159, 92), 702),
        "day": ((496, 46), (244, 222, 154), 703),
    }
    for index, (name, colors) in enumerate(TRAIN_SKIES.items()):
        base = _sky(colors, 100 + index)
        if name == "night":
            for star in range(52):
                x = (star * 103 + 29) % LOW_SIZE[0]
                y = (star * 47 + 17) % 104
                shade = 119 + star % 4 * 22
                base.set_at((x, y), (shade, shade + 7, min(255, shade + 18), 255))
        cloud_color = {
            "night": (55, 66, 85, 255),
            "dawn": (173, 98, 91, 255),
            "day": (157, 187, 198, 255),
        }[name]
        for cloud in range(5):
            x = 40 + cloud * 127
            y = 67 + cloud * 19 % 43
            pygame.draw.rect(base, cloud_color, (x, y, 54 + cloud % 3 * 13, 2))
            pygame.draw.rect(base, cloud_color, (x + 14, y - 2, 24 + cloud % 2 * 11, 2))
        center, color, seed = discs[name]
        _textured_disc(base, center, 17, color, seed)
        pygame.draw.line(base, (*tuple(max(0, value - 12) for value in color), 90),
                         (center[0] - 22, center[1] + 21), (center[0] + 19, center[1] + 23), 1)
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
