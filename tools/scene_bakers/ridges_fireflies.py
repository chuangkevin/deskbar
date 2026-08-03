"""Bake dimensional mountain-ridge and grounded firefly-meadow layers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from tools.scene_bakers.common import WORK_SIZE, feather_alpha, fbm, save_rgba


FloatArray = NDArray[np.float32]
RIDGE_PALETTES: Final = {
    "night": ((6, 12, 28), (42, 62, 88), (116, 150, 184)),
    "dawn": ((31, 28, 57), (171, 105, 105), (246, 180, 129)),
    "day": ((49, 104, 151), (177, 207, 221), (238, 224, 194)),
}
MEADOW_PALETTES: Final = {
    "night": ((5, 12, 25), (30, 49, 55), (17, 35, 28)),
    "dawn": ((37, 29, 52), (148, 91, 93), (42, 57, 37)),
    "day": ((72, 124, 155), (190, 190, 155), (56, 83, 48)),
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


def generate_ridge_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 2100, octaves=4, base=7)
    for name, (top, bottom, glow) in RIDGE_PALETTES.items():
        base = _gradient(top, bottom)
        base += (noise[..., None] - 0.5) * 0.045
        horizon = np.exp(-((y - height * 0.58) / (height * 0.17)) ** 2)[..., None]
        base += horizon * _color(glow)[None, None, :] * (0.14 if name != "night" else 0.07)
        save_rgba(out / f"ridges_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    specifications = (
        ("far", 0.43, 0.12, 2301, 0.82),
        ("mid", 0.58, 0.15, 2402, 0.68),
        ("near", 0.72, 0.17, 2503, 0.54),
    )
    for name, base_y, amplitude, seed, luminance_floor in specifications:
        profile_noise = fbm(width, 8, seed, octaves=4, base=3).mean(axis=0)
        profile = height * (
            base_y + (profile_noise - 0.5) * amplitude
            + np.sin(np.arange(width, dtype=np.float32) * 0.006 + seed) * 0.025
        )
        depth = y - profile[None, :]
        alpha = np.clip(depth / 3.0, 0.0, 1.0)
        alpha = feather_alpha(np.asarray(alpha, np.float32), 6, 3)
        texture = fbm(width, height, seed + 31, octaves=4, base=11)
        relief = texture - np.roll(texture, shift=(8, -11), axis=(0, 1))
        luminance = np.clip(
            luminance_floor + texture * 0.22 + relief * 0.75
            + np.clip(1.0 - depth / 70.0, 0.0, 1.0) * 0.13
            - np.clip(depth / height, 0.0, 1.0) * 0.20,
            0.12,
            1.0,
        )
        rgb = np.repeat(luminance[..., None], 3, axis=2)
        save_rgba(out / f"ridges_{name}.png", _rgba(rgb, alpha), True)
    fog_alpha = np.exp(-((y - height * 0.60) / (height * 0.07)) ** 2) * (0.18 + noise * 0.25)
    fog_alpha = feather_alpha(np.asarray(fog_alpha, np.float32), 72, 20)
    fog_rgb = np.broadcast_to(_color((218, 229, 234)), (height, width, 3)).copy()
    save_rgba(out / "ridges_fog.png", _rgba(fog_rgb, fog_alpha), True)
    shadow_alpha = np.exp(-((y - height * 0.72) / (height * 0.15)) ** 2) * np.clip(noise - 0.44, 0.0, 0.36)
    shadow_alpha = feather_alpha(np.asarray(shadow_alpha, np.float32), 72, 24)
    shadow_rgb = np.zeros((height, width, 3), dtype=np.float32)
    save_rgba(out / "ridges_shadow.png", _rgba(shadow_rgb, shadow_alpha), True)


def generate_firefly_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 3100, octaves=4, base=8)
    for name, (top, horizon, meadow) in MEADOW_PALETTES.items():
        base = _gradient(top, horizon)
        meadow_edge = height * (0.66 + np.sin(x * 0.011) * 0.018 + (noise - 0.5) * 0.04)
        ground = y >= meadow_edge
        meadow_rgb = _color(meadow)[None, None, :] * (0.64 + noise[..., None] * 0.40)
        base[ground] = meadow_rgb[ground]
        base += np.exp(-((y - height * 0.58) / (height * 0.20)) ** 2)[..., None] \
            * _color((235, 185, 109))[None, None, :] * (0.08 if name == "night" else 0.14)
        save_rgba(out / f"fireflies_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    for layer, edge, seed, color in (
        ("far", 0.68, 3210, (91, 115, 74)),
        ("near", 0.79, 3320, (32, 58, 38)),
    ):
        grass_noise = fbm(width, height, seed, octaves=3, base=18)
        blade = np.sin(x * (0.14 if layer == "far" else 0.21) + grass_noise * 7.0)
        grass_edge = height * (edge - np.maximum(blade, 0.0) * (0.035 if layer == "far" else 0.065))
        alpha = (y >= grass_edge).astype(np.float32)
        alpha = feather_alpha(alpha, 5, 3)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        rgb *= 0.72 + grass_noise[..., None] * 0.28
        save_rgba(out / f"fireflies_grass_{layer}.png", _rgba(rgb, alpha), True)
    haze_alpha = np.exp(-((y - height * 0.64) / (height * 0.10)) ** 2) * (0.12 + noise * 0.16)
    haze_alpha = feather_alpha(np.asarray(haze_alpha, np.float32), 72, 24)
    haze_rgb = np.broadcast_to(_color((213, 185, 133)), (height, width, 3)).copy()
    save_rgba(out / "fireflies_haze.png", _rgba(haze_rgb, haze_alpha), True)
    distance = np.sqrt((x - width * 0.5) ** 2 + (y - height * 0.5) ** 2)
    for index, (radius, color) in enumerate(((15.0, (221, 239, 123)), (26.0, (249, 201, 91)))):
        core = np.exp(-(distance / (radius * 0.24)) ** 2)
        glow = np.exp(-(distance / radius) ** 2) * 0.55
        alpha = feather_alpha(np.asarray(np.clip(core + glow, 0.0, 1.0), np.float32), 4, 4)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        save_rgba(out / f"fireflies_glow_{index}.png", _rgba(rgb, alpha), True)


def generate_ridges_fireflies_assets(out: Path) -> None:
    generate_ridge_assets(out)
    generate_firefly_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate_ridges_fireflies_assets(args.out)


if __name__ == "__main__":
    main()
