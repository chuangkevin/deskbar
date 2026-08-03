"""Bake astrophotographic stars and volumetric aurora scene layers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from tools.scene_bakers.common import WORK_SIZE, feather_alpha, fbm, save_rgba


FloatArray = NDArray[np.float32]
STAR_PALETTES: Final = {
    "night": ((2, 5, 18), (22, 31, 62), (123, 151, 205)),
    "dawn": ((24, 20, 48), (124, 81, 103), (224, 161, 146)),
    "day": ((38, 91, 139), (139, 187, 214), (224, 235, 236)),
}
AURORA_PALETTES: Final = {
    "night": ((2, 8, 22), (14, 31, 52), (10, 20, 29)),
    "dawn": ((24, 26, 55), (105, 78, 105), (27, 34, 48)),
    "day": ((47, 101, 145), (151, 190, 208), (49, 72, 79)),
}


def _color(rgb: tuple[int, int, int]) -> FloatArray:
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _rgba(rgb: FloatArray, alpha: FloatArray) -> FloatArray:
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha[..., None]), axis=2)


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> FloatArray:
    width, height = WORK_SIZE
    amount = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    row = _color(top)[None, None, :] + (_color(bottom) - _color(top))[None, None, :] * amount
    return np.broadcast_to(row, (height, width, 3)).copy()


def generate_stars_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    dust = fbm(width, height, 3300, octaves=5, base=5)
    detail = fbm(width, height, 3410, octaves=3, base=23)
    diagonal = np.exp(-((y - height * 0.54 - (x - width * 0.5) * 0.16) / (height * 0.19)) ** 2)
    lane = diagonal * np.clip(dust * 0.75 + detail * 0.25, 0.0, 1.0)
    for name, (top, bottom, glow) in STAR_PALETTES.items():
        base = _gradient(top, bottom)
        base += (dust[..., None] - 0.5) * 0.075
        base = base * (1.0 - lane[..., None] * 0.34) + _color(glow)[None, None, :] * lane[..., None] * 0.22
        generator = np.random.default_rng(4100 + len(name))
        count = 420 if name == "night" else 110 if name == "dawn" else 24
        for _ in range(count):
            star_x = int(generator.integers(3, width - 3))
            star_y = int(generator.integers(3, round(height * 0.82)))
            intensity = float(generator.uniform(0.18, 0.72))
            base[star_y - 1:star_y + 2, star_x - 1:star_x + 2] += intensity
        save_rgba(out / f"stars_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    for layer, shift, strength, color in (
        ("far", 0.0, 0.22, (117, 145, 196)),
        ("near", 0.11, 0.30, (192, 177, 202)),
    ):
        band = np.exp(-((y - height * (0.49 + shift) - (x - width * 0.5) * 0.14) / (height * 0.17)) ** 2)
        alpha = feather_alpha(np.asarray(band * np.clip(dust - 0.30, 0.0, 1.0) * strength, np.float32), 72, 32)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        save_rgba(out / f"stars_dust_{layer}.png", _rgba(rgb, alpha), True)
    for index, (radius, color) in enumerate(((5.0, (210, 225, 255)), (8.0, (255, 232, 190)), (12.0, (185, 216, 255)))):
        distance = np.sqrt((x - width * 0.5) ** 2 + (y - height * 0.5) ** 2)
        alpha = np.exp(-(distance / radius) ** 2)
        rays = np.exp(-np.abs(x - width * 0.5) / (radius * 0.45)) * np.exp(-np.abs(y - height * 0.5) / (radius * 4.0))
        rays += np.exp(-np.abs(y - height * 0.5) / (radius * 0.45)) * np.exp(-np.abs(x - width * 0.5) / (radius * 4.0))
        alpha = feather_alpha(np.asarray(np.clip(alpha + rays * 0.36, 0.0, 1.0), np.float32), 4, 4)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        save_rgba(out / f"stars_sprite_{index}.png", _rgba(rgb, alpha), True)
    along = (x - width * 0.5) + (y - height * 0.42) * 2.6
    across = (y - height * 0.42) - (x - width * 0.5) * 0.22
    meteor_alpha = np.exp(-(across / 6.0) ** 2) * np.exp(-np.clip(-along, 0.0, 260.0) / 88.0)
    meteor_alpha *= (along <= 20) & (along >= -300)
    meteor_alpha = feather_alpha(np.asarray(meteor_alpha, np.float32), 4, 4)
    meteor_rgb = np.broadcast_to(_color((255, 231, 194)), (height, width, 3)).copy()
    save_rgba(out / "stars_meteor.png", _rgba(meteor_rgb, meteor_alpha), True)


def generate_aurora_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 5100, octaves=4, base=7)
    ridge = height * (0.72 + 0.05 * np.sin(x * 0.006) + 0.035 * np.sin(x * 0.017 + 1.2))
    far_ridge = height * (0.65 + 0.035 * np.sin(x * 0.004 + 0.8)
                          + 0.018 * np.sin(x * 0.013))
    for name, (top, bottom, land) in AURORA_PALETTES.items():
        base = _gradient(top, bottom)
        base += (noise[..., None] - 0.5) * 0.045
        far_ground = y >= far_ridge
        far_rgb = (_color(land) * 0.72 + _color(bottom) * 0.28)[None, None, :] \
            * (0.82 + noise[..., None] * 0.18)
        base[far_ground] = far_rgb[far_ground]
        ground = y >= ridge
        land_rgb = _color(land)[None, None, :] * (0.62 + noise[..., None] * 0.38)
        base[ground] = land_rgb[ground]
        save_rgba(out / f"aurora_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    curtain_colors = ((75, 225, 172), (102, 165, 238), (188, 116, 215))
    for index, color in enumerate(curtain_colors):
        wave = height * (0.22 + index * 0.055) + np.sin(x * (0.004 + index * 0.0008) + index * 1.7) * (55 + index * 12)
        distance = y - wave
        upper = np.exp(-(distance / (22 + index * 4)) ** 2)
        curtain = np.exp(-np.clip(distance, 0.0, height) / (105 + index * 22)) * (distance >= 0)
        striation = 0.38 + 0.62 * np.clip(np.sin(x * (0.050 + index * 0.011) + noise * 5.0), 0.0, 1.0)
        volume = np.exp(-((distance - 62 - index * 14) / (76 + index * 11)) ** 2)
        alpha = np.clip(upper * 0.30 + curtain * striation * 0.34 + volume * striation * 0.16,
                        0.0, 0.74)
        alpha *= np.clip((ridge - y) / (height * 0.16), 0.0, 1.0)
        alpha = feather_alpha(np.asarray(alpha, np.float32), 72, 32)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        save_rgba(out / f"aurora_curtain_{index}.png", _rgba(rgb, alpha), True)


def generate_stars_aurora_assets(out: Path) -> None:
    generate_stars_assets(out)
    generate_aurora_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate_stars_aurora_assets(args.out)


if __name__ == "__main__":
    main()
