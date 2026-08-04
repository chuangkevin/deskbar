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
    "night": (
        (2, 5, 11), (7, 15, 22), (8, 27, 39),
        (27, 87, 102), (94, 175, 177), (188, 101, 63),
    ),
    "dawn": (
        (15, 8, 18), (29, 15, 27), (48, 25, 40),
        (124, 59, 66), (213, 127, 91), (75, 151, 157),
    ),
    "day": (
        (8, 24, 31), (15, 38, 43), (20, 55, 62),
        (51, 107, 111), (151, 185, 168), (190, 119, 78),
    ),
}
FLOW_CURVE: Final = (
    (-0.08, 0.32),
    (0.12, 0.12),
    (0.28, 0.16),
    (0.43, 0.55),
    (0.58, 0.94),
    (0.75, 0.82),
    (1.08, 0.37),
)


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


def _cubic_segment(points: FloatArray, amount: FloatArray) -> FloatArray:
    inverse = 1.0 - amount
    return (
        inverse[:, None] ** 3 * points[0]
        + 3.0 * inverse[:, None] ** 2 * amount[:, None] * points[1]
        + 3.0 * inverse[:, None] * amount[:, None] ** 2 * points[2]
        + amount[:, None] ** 3 * points[3]
    )


def _flow_distance(width: int, height: int) -> tuple[FloatArray, FloatArray]:
    """Return distance from, and progress along, one authored S-current."""
    points = np.asarray(FLOW_CURVE, dtype=np.float32)
    amount = np.linspace(0.0, 1.0, 768, dtype=np.float32)
    first = _cubic_segment(points[:4], amount)
    second = _cubic_segment(points[3:], amount)
    curve = np.concatenate((first[:-1], second), axis=0)
    columns = np.arange(width, dtype=np.float32)
    center = np.interp(
        columns,
        curve[:, 0] * width,
        curve[:, 1] * height,
    ).astype(np.float32)
    slope = np.gradient(center).astype(np.float32)
    rows = np.arange(height, dtype=np.float32)[:, None]
    distance = (rows - center[None, :]) / np.sqrt(1.0 + slope[None, :] ** 2)
    progress = np.broadcast_to(columns[None, :] / width, (height, width))
    return np.asarray(distance, dtype=np.float32), np.asarray(progress, dtype=np.float32)


def _soft_band(distance: FloatArray, half_width: float, feather: float) -> FloatArray:
    amount = np.clip(
        (half_width + feather - np.abs(distance)) / (2.0 * feather),
        0.0,
        1.0,
    )
    return np.asarray(amount * amount * (3.0 - 2.0 * amount), dtype=np.float32)


def _blend(rgb: FloatArray, color: tuple[int, int, int], amount: FloatArray) -> FloatArray:
    return (
        rgb * (1.0 - amount[..., None])
        + _color(color)[None, None, :] * amount[..., None]
    )


def _flow_brush(index: int, width: int, height: int) -> FloatArray:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    dx = x - width * 0.5
    dy = y - height * 0.5
    half_length = (148.0, 104.0)[index]
    unit_x = dx / half_length
    taper = np.clip(1.0 - np.abs(unit_x), 0.0, 1.0)
    taper = taper * taper * (3.0 - 2.0 * taper)
    generator = np.random.default_rng(6840 + index)
    control_x = np.linspace(-1.0, 1.0, 15, dtype=np.float32)
    control_strength = generator.uniform(0.48, 1.0, len(control_x)).astype(np.float32)
    dry_brush = np.interp(unit_x, control_x, control_strength).astype(np.float32)
    alpha = np.zeros((height, width), dtype=np.float32)
    offsets = ((-11.0, -3.0, 4.0, 11.0), (-7.0, -1.0, 5.0))[index]
    for fiber, offset in enumerate(offsets):
        bend = (fiber - len(offsets) * 0.5) * unit_x * unit_x * 1.5
        thickness = 1.7 + (fiber % 2) * 0.9
        alpha += (
            np.exp(-0.5 * ((dy - offset - bend) / thickness) ** 2)
            * (0.22 + fiber * 0.035)
        )
    body_width = (12.0, 8.0)[index]
    alpha += np.exp(-0.5 * (dy / body_width) ** 2) * 0.18
    alpha = np.clip(alpha * taper * dry_brush, 0.0, 0.92)
    alpha = feather_alpha(np.asarray(alpha, dtype=np.float32), 8, 8)
    cool = _color((101, 205, 213))
    warm = _color((228, 139, 82))
    rgb_color = warm if index == 0 else cool
    luminance = (0.82 + dry_brush * 0.18)[..., None]
    rgb = np.broadcast_to(rgb_color, (height, width, 3)).copy() * luminance
    return _rgba(rgb, alpha)


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
    distance, progress = _flow_distance(width, height)
    broad_noise = fbm(width, height, 6200, octaves=4, base=5)
    detail = fbm(width, height, 6490, octaves=4, base=17)
    edge_warp = (broad_noise - 0.5) * height * 0.025 + (detail - 0.5) * height * 0.008
    outer = _soft_band(distance + edge_warp, height * 0.155, height * 0.045)
    main = _soft_band(distance + edge_warp * 0.72, height * 0.088, height * 0.022)
    upper = _soft_band(
        distance + height * 0.112 + edge_warp * 0.45,
        height * 0.034,
        height * 0.014,
    )
    lower = _soft_band(
        distance - height * 0.112 + edge_warp * 0.38,
        height * 0.027,
        height * 0.012,
    )
    upper_span = np.clip(
        0.24 + np.exp(-((progress - 0.38) / 0.33) ** 2),
        0.0,
        1.0,
    )
    lower_span = np.clip(
        np.exp(-((progress - 0.66) / 0.29) ** 2)
        + np.exp(-((progress - 0.08) / 0.12) ** 2) * 0.46,
        0.0,
        1.0,
    )
    granulation = 0.66 + broad_noise * 0.24 + detail * 0.10
    for name, (top, bottom, shadow, ink, light, warm) in FLOW_PALETTES.items():
        base = _vertical_gradient(top, bottom)
        base *= (0.92 + broad_noise[..., None] * 0.11)
        base = _blend(base, shadow, outer * (0.19 + broad_noise * 0.12))
        base = _blend(base, ink, main * granulation * 0.78)
        base = _blend(base, light, upper * upper_span * (0.47 + detail * 0.23))
        base = _blend(base, warm, lower * lower_span * (0.50 + broad_noise * 0.22))
        wet_glint = _soft_band(
            distance + height * 0.040 + (detail - 0.5) * height * 0.010,
            height * 0.006,
            height * 0.004,
        )
        base = _blend(base, light, wet_glint * (0.12 + detail * 0.18))
        save_rgba(
            out / f"flow_base_{name}.png",
            _rgba(base, np.ones((height, width), np.float32)),
            False,
        )

    generator = np.random.default_rng(6720)
    veil_alpha = np.zeros((height, width), dtype=np.float32)
    offsets = (-0.105, -0.073, -0.040, -0.014, 0.018, 0.052, 0.091)
    columns = np.arange(width, dtype=np.float32) / width
    control_x = np.linspace(0.0, 1.0, 13, dtype=np.float32)
    for index, offset in enumerate(offsets):
        controls = generator.normal(0.0, height * 0.006, len(control_x)).astype(np.float32)
        jitter = np.interp(columns, control_x, controls).astype(np.float32)[None, :]
        thickness = height * (0.0015 + (index % 3) * 0.00045)
        fiber = np.exp(
            -0.5 * ((distance - height * offset - jitter) / thickness) ** 2
        )
        center = 0.18 + index * 0.105
        span = np.clip(
            np.exp(-((progress - center) / (0.34 + index % 2 * 0.10)) ** 2) * 1.3,
            0.0,
            1.0,
        )
        tooth = 0.42 + detail * 0.58
        veil_alpha += fiber * span * tooth * (0.20 + (index % 2) * 0.07)
    veil_alpha = feather_alpha(np.clip(veil_alpha, 0.0, 0.70), 120, 48)
    warm_mix = np.clip(0.45 + distance / (height * 0.30), 0.0, 1.0)[..., None]
    cool = _color((94, 202, 211))[None, None, :]
    warm = _color((221, 132, 78))[None, None, :]
    veil_rgb = (cool * (1.0 - warm_mix) + warm * warm_mix) * (
        0.82 + detail[..., None] * 0.18
    )
    save_rgba(out / "flow_filament_veil.png", _rgba(veil_rgb, veil_alpha), True)
    for index in range(2):
        save_rgba(out / f"flow_brush_{index}.png", _flow_brush(index, width, height), True)


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
