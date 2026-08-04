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


def _draw_runner(surface: pygame.Surface, origin: tuple[int, int], step: int) -> None:
    """Draw a compact, hard-edged 8-bit red-capped platform hero."""
    x, y = origin
    standing = (
        "....RRRRR.......", "...RRRRRRRR.....", "...BBBSSB.......",
        "..BSSSSSBBB.....", "..BSSSSSSBBB....", "..BBSSSSBBBB....",
        "....SSSSSS......", "...RRBRRR.......", "..RRRBRRBRRR....",
        ".RRRRBBBBRRRR...", ".SSRBBOBBBRSS...", ".SSSBBBBBBSSS...",
        "...BBBBBBBB.....", "...BBB..BBB.....", "..BBB....BBB....",
        ".DDDD....DDDD...", "DDDDD....DDDDD..",
    )
    running = standing[:-4] + (
        "....BBBBBBB.....", "..BBBBBB........", ".DDDBBB...DDDD...",
        "DDDD.....DDDDD..",
    )
    palette = {
        "R": (216, 40, 24, 255),
        "S": (252, 168, 88, 255),
        "B": (112, 48, 24, 255),
        "O": (252, 216, 88, 255),
        "D": (48, 32, 24, 255),
    }
    for row, pixels in enumerate(running if step else standing):
        for column, pixel in enumerate(pixels):
            if pixel != ".":
                pygame.draw.rect(
                    surface,
                    palette[pixel],
                    (x + column * 2, y + row * 2, 2, 2),
                )


def _runner_ground(base: pygame.Surface, name: str, seed: int) -> None:
    width, height = LOW_SIZE
    pygame.draw.rect(base, (216, 72, 24, 255), (0, 190, width, height - 190))


def _draw_block(surface: pygame.Surface, x: int, y: int, question: bool = False) -> None:
    dark = (48, 24, 16, 255)
    orange = (232, 80, 24, 255)
    light = (252, 168, 56, 255)
    pygame.draw.rect(surface, dark, (x, y, 16, 16))
    pygame.draw.rect(surface, orange, (x + 2, y + 2, 12, 12))
    pygame.draw.line(surface, light, (x + 2, y + 2), (x + 13, y + 2), 2)
    pygame.draw.line(surface, light, (x + 2, y + 2), (x + 2, y + 12), 2)
    if question:
        pygame.draw.rect(surface, dark, (x + 6, y + 4, 5, 2))
        pygame.draw.rect(surface, dark, (x + 10, y + 6, 2, 3))
        pygame.draw.rect(surface, dark, (x + 7, y + 8, 4, 2))
        pygame.draw.rect(surface, dark, (x + 7, y + 12, 2, 2))
    else:
        pygame.draw.line(surface, dark, (x + 1, y + 8), (x + 14, y + 8), 2)
        pygame.draw.line(surface, dark, (x + 7, y + 1), (x + 7, y + 8), 2)


def _draw_pipe(surface: pygame.Surface, x: int, height: int) -> None:
    y = 190 - height
    dark = (24, 72, 16, 255)
    green = (0, 168, 40, 255)
    light = (128, 232, 56, 255)
    pygame.draw.rect(surface, dark, (x + 3, y + 7, 22, height - 7))
    pygame.draw.rect(surface, green, (x + 6, y + 7, 16, height - 7))
    pygame.draw.rect(surface, light, (x + 8, y + 7, 4, height - 7))
    pygame.draw.rect(surface, dark, (x, y, 28, 9))
    pygame.draw.rect(surface, green, (x + 2, y + 2, 24, 5))
    pygame.draw.rect(surface, light, (x + 6, y + 2, 5, 5))


def _draw_goomba(surface: pygame.Surface, x: int, y: int) -> None:
    dark = (48, 24, 16, 255)
    brown = (184, 72, 32, 255)
    light = (252, 168, 88, 255)
    pygame.draw.rect(surface, dark, (x + 4, y, 8, 2))
    pygame.draw.rect(surface, brown, (x + 2, y + 2, 12, 7))
    pygame.draw.rect(surface, brown, (x, y + 5, 16, 5))
    pygame.draw.rect(surface, light, (x + 3, y + 6, 3, 4))
    pygame.draw.rect(surface, light, (x + 10, y + 6, 3, 4))
    pygame.draw.rect(surface, dark, (x + 4, y + 6, 2, 3))
    pygame.draw.rect(surface, dark, (x + 10, y + 6, 2, 3))
    pygame.draw.rect(surface, light, (x + 5, y + 10, 6, 3))
    pygame.draw.rect(surface, dark, (x + 1, y + 13, 6, 3))
    pygame.draw.rect(surface, dark, (x + 9, y + 13, 6, 3))


def generate_runner_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = LOW_SIZE
    for index, name in enumerate(RUNNER_SKIES):
        base = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
        base.fill((92, 148, 252, 255))
        _runner_ground(base, name, 910 + index)
        _save(out / f"runner_base_{name}.png", base, False)

    far = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for cloud_x, cloud_y in ((48, 35), (255, 59), (474, 27)):
        pygame.draw.polygon(far, (48, 32, 24, 255),
                            ((cloud_x, cloud_y + 13), (cloud_x + 7, cloud_y + 7),
                             (cloud_x + 14, cloud_y + 7), (cloud_x + 19, cloud_y),
                             (cloud_x + 27, cloud_y), (cloud_x + 33, cloud_y + 7),
                             (cloud_x + 42, cloud_y + 7), (cloud_x + 50, cloud_y + 15),
                             (cloud_x + 46, cloud_y + 19), (cloud_x + 5, cloud_y + 19)))
        pygame.draw.polygon(far, (252, 252, 252, 255),
                            ((cloud_x + 3, cloud_y + 13), (cloud_x + 10, cloud_y + 9),
                             (cloud_x + 17, cloud_y + 10), (cloud_x + 21, cloud_y + 3),
                             (cloud_x + 27, cloud_y + 3), (cloud_x + 32, cloud_y + 10),
                             (cloud_x + 40, cloud_y + 10), (cloud_x + 46, cloud_y + 15),
                             (cloud_x + 43, cloud_y + 17), (cloud_x + 7, cloud_y + 17)))
        pygame.draw.line(far, (88, 216, 248, 255),
                         (cloud_x + 10, cloud_y + 15), (cloud_x + 20, cloud_y + 17), 2)
    _save(out / "runner_far.png", far, True)

    mid = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for hill_x in (-35, 225, 490):
        pygame.draw.polygon(mid, (24, 72, 16, 255),
                            ((hill_x, 190), (hill_x + 22, 169), (hill_x + 37, 151),
                             (hill_x + 52, 141), (hill_x + 68, 154),
                             (hill_x + 91, 177), (hill_x + 106, 190)))
        pygame.draw.polygon(mid, (0, 184, 48, 255),
                            ((hill_x + 5, 190), (hill_x + 27, 170), (hill_x + 42, 154),
                             (hill_x + 52, 146), (hill_x + 63, 158),
                             (hill_x + 85, 180), (hill_x + 96, 190)))
        pygame.draw.rect(mid, (48, 112, 24, 255), (hill_x + 47, 161, 4, 7))
        pygame.draw.rect(mid, (48, 112, 24, 255), (hill_x + 68, 174, 4, 7))
    for bush_x in (94, 374):
        pygame.draw.rect(mid, (24, 72, 16, 255), (bush_x, 178, 76, 12))
        pygame.draw.circle(mid, (0, 184, 48, 255), (bush_x + 16, 178), 15)
        pygame.draw.circle(mid, (0, 184, 48, 255), (bush_x + 38, 171), 20)
        pygame.draw.circle(mid, (0, 184, 48, 255), (bush_x + 61, 179), 14)
    _save(out / "runner_mid.png", mid, True)

    near = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for tile_y in range(190, height, 16):
        offset = -8 if (tile_y // 16) % 2 else 0
        for tile_x in range(offset, width, 16):
            pygame.draw.rect(near, (48, 24, 16, 255), (tile_x, tile_y, 16, 16))
            pygame.draw.rect(near, (232, 80, 24, 255), (tile_x + 2, tile_y + 2, 13, 13))
            pygame.draw.line(near, (252, 168, 56, 255),
                             (tile_x + 2, tile_y + 2), (tile_x + 14, tile_y + 2), 2)
            pygame.draw.line(near, (252, 168, 56, 255),
                             (tile_x + 2, tile_y + 2), (tile_x + 2, tile_y + 13), 2)
    _save(out / "runner_near.png", near, True)

    sheet = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner(sheet, (width // 2 - 28, height // 2 - 12), 0)
    _draw_runner(sheet, (width // 2 + 12, height // 2 - 12), 1)
    _save(out / "runner_sprite_sheet.png", sheet, True)

    obstacles = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for index, x in enumerate(range(105, width, 73)):
        if index % 3 == 0:
            _draw_pipe(obstacles, x, 32 + index % 2 * 8)
        elif index % 3 == 1:
            _draw_goomba(obstacles, x + 6, 174)
        else:
            _draw_block(obstacles, x, 142, question=True)
            _draw_block(obstacles, x - 16, 142)
            _draw_block(obstacles, x + 16, 142)
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
