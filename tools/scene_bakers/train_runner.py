"""Bake original cinematic pixel-train and pixel-runner worlds."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import pygame


LOW_SIZE: Final = (620, 236)
OUTPUT_SIZE: Final = (1240, 472)
TRAIN_SKIES: Final = {
    "night": ((10, 17, 40), (48, 59, 89)),
    "dawn": ((54, 38, 67), (218, 128, 93)),
    "day": ((63, 127, 177), (183, 211, 220)),
}
RUNNER_SKIES: Final = {
    "night": ((17, 22, 48), (71, 65, 88)),
    "dawn": ((74, 48, 70), (231, 151, 102)),
    "day": ((78, 151, 193), (208, 218, 188)),
}


def _lerp(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * amount) for a, b in zip(first, second))


def _save(path: Path, source: pygame.Surface, transparent: bool) -> None:
    output = pygame.transform.scale(source, OUTPUT_SIZE)
    alpha = pygame.surfarray.pixels_alpha(output)
    if transparent:
        alpha[0, :] = alpha[-1, :] = 0
        alpha[:, 0] = alpha[:, -1] = 0
    else:
        alpha[:, :] = 255
    del alpha
    pygame.image.save(output, path)


def _sky(colors: tuple[tuple[int, int, int], tuple[int, int, int]], seed: int) -> pygame.Surface:
    width, height = LOW_SIZE
    surface = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for y in range(height):
        color = _lerp(colors[0], colors[1], y / (height - 1))
        surface.fill((*color, 255), pygame.Rect(0, y, width, 1))
    for index in range(280):
        x = (index * 83 + seed * 17) % width
        y = (index * 47 + seed * 29) % round(height * 0.72)
        base = surface.get_at((x, y))
        shift = (index % 7) - 3
        surface.set_at((x, y), (
            max(0, min(255, base.r + shift)),
            max(0, min(255, base.g + shift)),
            max(0, min(255, base.b + shift)),
            255,
        ))
    return surface


def generate_train_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = LOW_SIZE
    for index, (name, colors) in enumerate(TRAIN_SKIES.items()):
        base = _sky(colors, 100 + index)
        glow = (240, 183, 114) if name != "day" else (232, 226, 177)
        pygame.draw.circle(base, (*glow, 255), (round(width * 0.78), round(height * 0.34)), 18)
        _save(out / f"train_base_{name}.png", base, False)
    far = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for block in range(0, width, 18):
        building_height = 16 + (block * 7 % 42)
        pygame.draw.rect(far, (72, 86, 111, 230), (block, 138 - building_height, 16, building_height))
        for window_y in range(105, 136, 7):
            pygame.draw.rect(far, (204, 180, 112, 145), (block + 3, window_y, 2, 2))
    _save(out / "train_far.png", far, True)
    mid = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for stripe in range(7):
        color = (87 + stripe * 5, 119 + stripe * 6, 70 + stripe * 3, 235)
        pygame.draw.rect(mid, color, (0, 132 + stripe * 15, width, 16))
    for x in range(0, width, 31):
        pygame.draw.line(mid, (204, 196, 139, 165), (x, 138), (x + 22, height - 2), 1)
    _save(out / "train_mid.png", mid, True)
    near = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for x in range(12, width, 76):
        pygame.draw.rect(near, (24, 27, 34, 255), (x, 18, 3, height - 22))
        pygame.draw.rect(near, (24, 27, 34, 255), (x - 8, 25, 19, 3))
    pygame.draw.line(near, (29, 31, 38, 235), (0, 31), (width, 37), 2)
    pygame.draw.line(near, (29, 31, 38, 235), (0, 39), (width, 45), 1)
    _save(out / "train_near.png", near, True)
    reflection = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for offset in range(-height, width, 84):
        pygame.draw.line(reflection, (220, 235, 240, 24), (offset, 0), (offset + 120, height), 11)
    pygame.draw.rect(reflection, (8, 11, 18, 110), (0, 0, width, 7))
    pygame.draw.rect(reflection, (8, 11, 18, 120), (0, height - 9, width, 9))
    _save(out / "train_window_reflection.png", reflection, True)


def _draw_runner(surface: pygame.Surface, origin: tuple[int, int], step: int) -> None:
    x, y = origin
    palette = ((38, 91, 98), (218, 171, 129), (113, 75, 57), (38, 36, 42))
    pygame.draw.rect(surface, (*palette[0], 255), (x + 4, y + 4, 8, 8))
    pygame.draw.rect(surface, (*palette[1], 255), (x + 5, y + 1, 6, 5))
    pygame.draw.rect(surface, (*palette[2], 255), (x + 3, y + 11, 10, 7))
    if step == 0:
        pygame.draw.rect(surface, (*palette[3], 255), (x + 1, y + 18, 5, 3))
        pygame.draw.rect(surface, (*palette[3], 255), (x + 10, y + 18, 5, 3))
    else:
        pygame.draw.rect(surface, (*palette[3], 255), (x + 4, y + 18, 4, 4))
        pygame.draw.rect(surface, (*palette[3], 255), (x + 8, y + 18, 4, 4))


def generate_runner_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = LOW_SIZE
    for index, (name, colors) in enumerate(RUNNER_SKIES.items()):
        base = _sky(colors, 200 + index)
        ground = (36, 65, 46) if name != "night" else (24, 38, 34)
        pygame.draw.rect(base, (*ground, 255), (0, 178, width, height - 178))
        for y in range(178, height, 4):
            shade = 4 + (y - 178) // 4
            pygame.draw.line(base, (max(0, ground[0] - shade), max(0, ground[1] - shade),
                                    max(0, ground[2] - shade), 255), (0, y), (width, y))
        _save(out / f"runner_base_{name}.png", base, False)
    far = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    points = [(0, 151)] + [(x, 128 + (x * 17 % 29)) for x in range(0, width + 40, 40)] + [(width, 190)]
    pygame.draw.polygon(far, (91, 112, 105, 220), points)
    _save(out / "runner_far.png", far, True)
    mid = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for x in range(0, width, 34):
        pygame.draw.rect(mid, (48, 82, 57, 235), (x + 14, 135, 3, 44))
        pygame.draw.circle(mid, (63, 103, 65, 225), (x + 15, 132), 12)
    _save(out / "runner_mid.png", mid, True)
    near = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for x in range(0, width, 8):
        blade_height = 5 + (x * 11 % 13)
        pygame.draw.polygon(near, (24, 53, 33, 245), ((x, 190), (x + 3, 190 - blade_height), (x + 5, 190)))
    _save(out / "runner_near.png", near, True)
    sheet = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    _draw_runner(sheet, (width // 2 - 28, height // 2 - 12), 0)
    _draw_runner(sheet, (width // 2 + 12, height // 2 - 12), 1)
    _save(out / "runner_sprite_sheet.png", sheet, True)
    obstacles = pygame.Surface(LOW_SIZE, pygame.SRCALPHA)
    for x in range(30, width, 73):
        rock_height = 11 + (x * 5 % 12)
        color = (86 + x % 17, 78 + x % 13, 68 + x % 11, 255)
        pygame.draw.polygon(obstacles, color, ((x, 190), (x + 5, 190 - rock_height),
                                               (x + 17, 188 - rock_height // 2), (x + 23, 190)))
    _save(out / "runner_obstacles.png", obstacles, True)


def generate_train_runner_assets(out: Path) -> None:
    generate_train_assets(out)
    generate_runner_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pygame.init()
    generate_train_runner_assets(args.out)
    pygame.quit()


if __name__ == "__main__":
    main()
