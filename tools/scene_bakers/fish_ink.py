"""Bake original sumi-e fish, wake, paper, and pigment-bloom assets."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from tools.scene_bakers.common import WORK_SIZE, feather_alpha, fbm, save_rgba


FloatArray = NDArray[np.float32]
PAPER_PALETTES: Final = {
    "night": ((20, 27, 38), (44, 54, 66), (109, 132, 145)),
    "dawn": ((70, 57, 65), (137, 112, 103), (191, 153, 123)),
    "day": ((205, 200, 181), (231, 224, 197), (126, 153, 158)),
}
INK_PAPER_PALETTES: Final = {
    "night": ((17, 21, 30), (43, 48, 58), (75, 88, 101)),
    "dawn": ((79, 64, 68), (151, 127, 111), (107, 77, 82)),
    "day": ((219, 211, 187), (239, 230, 202), (103, 112, 118)),
}


def _color(rgb: tuple[int, int, int]) -> FloatArray:
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _rgba(rgb: FloatArray, alpha: FloatArray) -> FloatArray:
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha[..., None]), axis=2)


def _paper(palette: tuple[tuple[int, int, int], ...], noise: FloatArray) -> FloatArray:
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    amount = y[..., None] / height
    rgb = _color(palette[0])[None, None, :] + (
        _color(palette[1]) - _color(palette[0])
    )[None, None, :] * amount
    wash = np.sin(y * 0.022 + np.sin(x * 0.004) * 2.3) * 0.5 + 0.5
    rgb += (noise[..., None] - 0.5) * 0.11
    rgb += wash[..., None] * _color(palette[2])[None, None, :] * 0.065
    fibers = (np.sin(x * 0.41 + noise * 9.0) * 0.5 + 0.5) * 0.025
    return rgb + fibers[..., None]


def generate_fish_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 4300, octaves=4, base=9)
    for name, palette in PAPER_PALETTES.items():
        save_rgba(out / f"fish_base_{name}.png", _rgba(_paper(palette, noise), np.ones((height, width), np.float32)), False)
    center_x, center_y = width * 0.5, height * 0.5
    for index, (length, body_height, tilt) in enumerate(((175.0, 48.0, -0.10), (145.0, 60.0, 0.08), (205.0, 42.0, 0.02))):
        local_x = x - center_x
        local_y = y - center_y - local_x * tilt
        body = ((local_x / length) ** 2 + (local_y / body_height) ** 2) <= 1.0
        tail_x = (local_x + length * 1.18) / (length * 0.62)
        tail = (local_x < -length * 0.72) & (local_x > -length * 1.55) \
            & (np.abs(local_y) < (1.0 - np.clip(np.abs(tail_x), 0.0, 1.0)) * body_height * 1.8)
        fin = (local_x > -length * 0.1) & (local_x < length * 0.45) \
            & (local_y < -body_height * 0.45) \
            & (local_y > -body_height * 1.25 + (local_x / length) * body_height)
        alpha = (body | tail | fin).astype(np.float32)
        alpha *= 0.72 + noise * 0.28
        alpha = feather_alpha(alpha, 4, 4)
        luminance = np.clip(0.18 + noise * 0.34, 0.08, 0.62)
        rgb = np.repeat(luminance[..., None], 3, axis=2)
        save_rgba(out / f"fish_sprite_{index}.png", _rgba(rgb, alpha), True)
    for index, width_scale in enumerate((1.0, 1.35)):
        local_x = (x - center_x) / (230.0 * width_scale)
        local_y = (y - center_y) / 32.0
        wake = np.exp(-(local_y - np.sin(local_x * 8.0) * 0.34) ** 2 * 8.0) \
            * np.exp(-np.clip(-local_x, 0.0, 2.0) * 1.3) * (local_x <= 0.2)
        wake *= np.clip(1.0 - np.abs(local_x) / 1.8, 0.0, 1.0)
        alpha = feather_alpha(np.asarray(wake * 0.55, np.float32), 4, 4)
        rgb = np.broadcast_to(_color((92, 113, 125)), (height, width, 3)).copy()
        save_rgba(out / f"fish_wake_{index}.png", _rgba(rgb, alpha), True)


def generate_ink_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 5300, octaves=4, base=10)
    for name, palette in INK_PAPER_PALETTES.items():
        save_rgba(out / f"ink_base_{name}.png", _rgba(_paper(palette, noise), np.ones((height, width), np.float32)), False)
    distance = np.sqrt((x - width * 0.5) ** 2 + (y - height * 0.5) ** 2)
    angles = np.arctan2(y - height * 0.5, x - width * 0.5)
    colors = ((41, 76, 101), (118, 57, 75), (52, 96, 78))
    for index, color in enumerate(colors):
        radius = 112.0 + np.sin(angles * (5 + index) + noise * 5.0) * 28.0
        core = np.clip((radius - distance) / 26.0, 0.0, 1.0)
        bloom = np.exp(-(distance / (138.0 + index * 10.0)) ** 2) * (0.34 + noise * 0.34)
        veins = np.clip(np.sin(angles * (9 + index * 2) + distance * 0.045 + noise * 6.0), 0.0, 1.0)
        alpha = np.clip(core * (0.28 + noise * 0.44) + bloom * 0.34 + veins * bloom * 0.16, 0.0, 0.82)
        alpha = feather_alpha(np.asarray(alpha, np.float32), 4, 4)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        rgb *= 0.66 + noise[..., None] * 0.34
        save_rgba(out / f"ink_bloom_{index}.png", _rgba(rgb, alpha), True)


def generate_fish_ink_assets(out: Path) -> None:
    generate_fish_assets(out)
    generate_ink_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate_fish_ink_assets(args.out)


if __name__ == "__main__":
    main()
