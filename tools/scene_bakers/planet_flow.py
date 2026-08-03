"""Bake authored planet-horizon and luminous-flow production layers."""

from __future__ import annotations

import argparse
import gc
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from tools.scene_bakers.common import WORK_SIZE, feather_alpha, fbm, save_rgba


FloatArray = NDArray[np.float32]
PALETTES: Final = {
    "night": ((2, 8, 22), (14, 35, 62), (24, 43, 62), (86, 132, 168), (122, 205, 255)),
    "dawn": ((22, 25, 52), (126, 93, 112), (48, 49, 64), (158, 139, 145), (232, 196, 205)),
    "day": ((30, 76, 126), (139, 187, 210), (51, 69, 79), (175, 188, 189), (224, 246, 255)),
}
FLOW_PALETTES: Final = {
    "night": ((3, 7, 18), (15, 34, 58), (71, 125, 194), (220, 139, 83)),
    "dawn": ((27, 20, 34), (111, 61, 73), (232, 145, 97), (111, 192, 198)),
    "day": ((18, 51, 71), (99, 151, 165), (219, 231, 213), (42, 105, 139)),
}


def _color(rgb: tuple[int, int, int]) -> FloatArray:
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _rgba(rgb: FloatArray, alpha: FloatArray) -> FloatArray:
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha[..., None]), axis=2)


def _vertical_gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> FloatArray:
    width, height = WORK_SIZE
    amount = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    rgb = _color(top)[None, None, :] + (_color(bottom) - _color(top))[None, None, :] * amount
    return np.broadcast_to(rgb, (height, width, 3)).copy()


def _planet_layers(seed: int) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    center_x, center_y, radius = width * 0.57, -height * 0.31, height * 0.96
    px, py = (x - center_x) / radius, (y - center_y) / radius
    radial = np.sqrt(px * px + py * py)
    inside = radial <= 1.0
    normal_z = np.sqrt(np.clip(1.0 - radial * radial, 0.0, 1.0))
    broad = fbm(width, height, seed, octaves=4, base=4)
    detail = fbm(width, height, seed + 91, octaves=4, base=13)
    latitude = py + (broad - 0.5) * 0.12 + np.sin(px * 7 + broad * 4) * 0.025
    bands = np.clip(
        0.50 + np.sin(latitude * 42) * 0.20 + np.sin(latitude * 97 + detail * 8) * 0.09
        + (detail - 0.5) * 0.22,
        0.0,
        1.0,
    )
    illumination = np.clip(px * 0.24 + py * 0.72 + normal_z * 0.48 + 0.20, 0.0, 1.0)
    alpha = inside.astype(np.float32)
    alpha[[0, -1], :] = 0
    alpha[:, [0, -1]] = 0
    edge = np.abs(radial - 1.0) * radius
    rim_alpha = np.exp(-(edge / 3.0) ** 2) * np.clip(px * 0.75 + py * 0.55, 0.0, 1.0) ** 2
    rim_alpha = feather_alpha(np.asarray(rim_alpha, dtype=np.float32), 4, 4)
    return alpha, bands, illumination, rim_alpha


def generate_planet_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    noise = fbm(width, height, 7800, octaves=4, base=7)
    alpha, bands, illumination, rim_alpha = _planet_layers(7400)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    horizon_glow = np.exp(-((y - height * 0.63) / (height * 0.10)) ** 2)[..., None]
    for name, (zenith, horizon, shadow, lit, rim) in PALETTES.items():
        sky = _vertical_gradient(zenith, horizon)
        sky += (noise[..., None] - 0.5) * 0.035
        star_seed = np.random.default_rng(9000 + len(name))
        for _ in range(120 if name == "night" else 32):
            sx = int(star_seed.integers(4, width - 4))
            sy = int(star_seed.integers(4, round(height * 0.60)))
            sky[sy - 1:sy + 2, sx - 1:sx + 2] += 0.22 if name == "night" else 0.08
        sky += horizon_glow * _color(rim)[None, None, :] * (0.16 if name == "night" else 0.10)
        save_rgba(out / f"planet_sky_{name}.png", _rgba(sky, np.ones((height, width), np.float32)), False)
        body_amount = np.clip(0.05 + illumination * (0.34 + bands * 0.58), 0.0, 1.0)
        body_rgb = _color(shadow)[None, None, :] + (
            _color(lit) - _color(shadow)
        )[None, None, :] * body_amount[..., None]
        body_rgb *= 0.84 + bands[..., None] * 0.22
        save_rgba(out / f"planet_body_{name}.png", _rgba(body_rgb, alpha), True)
        rim_rgb = np.broadcast_to(_color(rim), (height, width, 3)).copy()
        save_rgba(out / f"planet_rim_{name}.png", _rgba(rim_rgb, rim_alpha), True)
        gc.collect()
    cloud_noise = fbm(width, height, 8110, octaves=4, base=9)
    cloud_detail = fbm(width, height, 8220, octaves=3, base=24)
    for layer, center, spread, strength in (("far", 0.68, 0.13, 0.55), ("near", 0.84, 0.17, 0.76)):
        band = np.exp(-((y / height - center) / spread) ** 2)
        density = np.clip((cloud_noise * 0.66 + cloud_detail * 0.34 - 0.47) * 4.0, 0.0, 1.0)
        cloud_alpha = feather_alpha(np.asarray(density * band * strength, np.float32), 72, 24)
        luminance = np.clip(0.42 + cloud_noise * 0.42 + cloud_detail * 0.18 - y / height * 0.10, 0.0, 1.0)
        cloud_rgb = np.repeat(luminance[..., None], 3, axis=2)
        save_rgba(out / f"planet_cloud_{layer}.png", _rgba(cloud_rgb, cloud_alpha), True)
    haze_band = np.exp(-((y - height * 0.63) / (height * 0.055)) ** 2) * 0.34
    haze_alpha = feather_alpha(np.asarray(haze_band, np.float32), 64, 16)
    haze_rgb = np.broadcast_to(_color((170, 220, 246)), (height, width, 3)).copy()
    save_rgba(out / "planet_haze.png", _rgba(haze_rgb, haze_alpha), True)


def generate_flow_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 6200, octaves=4, base=7)
    warped = np.sin(x * 0.010 + np.sin(y * 0.012) * 3.4 + noise * 5.0)
    ribbons = np.exp(-np.abs(warped) * 5.5)
    for name, (top, bottom, first, second) in FLOW_PALETTES.items():
        base = _vertical_gradient(top, bottom)
        accent_amount = np.clip(ribbons * 0.38 + (noise - 0.5) * 0.16, 0.0, 0.52)
        accent = _color(first)[None, None, :] * (0.55 + noise[..., None] * 0.45)
        base = base * (1.0 - accent_amount[..., None]) + accent * accent_amount[..., None]
        glow = np.exp(-((y - height * 0.66) / (height * 0.34)) ** 2)[..., None]
        base += glow * _color(second)[None, None, :] * 0.08
        save_rgba(out / f"flow_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    filament = np.exp(-np.abs(np.sin(x * 0.014 + np.sin(y * 0.019) * 2.2 + noise * 7.0)) * 10.0)
    veil_alpha = feather_alpha(np.asarray(filament * (0.10 + noise * 0.22), np.float32), 72, 32)
    veil_rgb = _color((104, 205, 224))[None, None, :] * (0.55 + noise[..., None] * 0.45)
    save_rgba(out / "flow_filament_veil.png", _rgba(veil_rgb, veil_alpha), True)
    for index, color in enumerate(((231, 151, 92), (108, 205, 222))):
        center_x, center_y = width * 0.5, height * 0.5
        dx, dy = (x - center_x) / 96.0, (y - center_y) / 28.0
        brush = np.exp(-(dx * dx + dy * dy) * 1.8)
        bristles = 0.42 + 0.58 * np.clip(np.sin((y - center_y) * (0.42 + index * 0.08)) * 2.0, 0.0, 1.0)
        brush_alpha = feather_alpha(np.asarray(brush * bristles * 0.88, np.float32), 4, 4)
        brush_rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        save_rgba(out / f"flow_brush_{index}.png", _rgba(brush_rgb, brush_alpha), True)


def generate_planet_flow_assets(out: Path) -> None:
    generate_planet_assets(out)
    generate_flow_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    generate_planet_flow_assets(args.out)


if __name__ == "__main__":
    main()
