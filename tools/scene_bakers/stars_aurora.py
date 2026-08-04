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
    "night": ((1, 5, 17), (14, 35, 48), (9, 23, 30), (3, 10, 14)),
    "dawn": ((15, 16, 40), (102, 74, 91), (42, 50, 63), (13, 20, 28)),
    "day": ((40, 96, 148), (151, 191, 211), (79, 103, 108), (28, 48, 55)),
}
AURORA_VIEW_WIDTH: Final = 1118


def _color(rgb: tuple[int, int, int]) -> FloatArray:
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _rgba(rgb: FloatArray, alpha: FloatArray) -> FloatArray:
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha[..., None]), axis=2)


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> FloatArray:
    width, height = WORK_SIZE
    amount = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    row = _color(top)[None, None, :] + (_color(bottom) - _color(top))[None, None, :] * amount
    return np.broadcast_to(row, (height, width, 3)).copy()


def _periodic_fbm_x(
    position: FloatArray,
    period: int,
    seed: int,
    base: int,
    octaves: int = 4,
) -> FloatArray:
    """Return seamless deterministic one-dimensional noise for a curtain tile."""
    normalized = np.mod(position, period) / period
    result = np.zeros_like(normalized, dtype=np.float32)
    amplitude = 1.0
    total = 0.0
    for octave in range(octaves):
        cells = base * 2 ** octave
        scaled = normalized * cells
        index = scaled.astype(np.int32)
        amount = np.asarray(scaled - index, dtype=np.float32)
        amount = amount * amount * (3.0 - 2.0 * amount)
        grid = np.random.default_rng(seed + octave * 97).random(cells, dtype=np.float32)
        result += (
            grid[index % cells] * (1.0 - amount)
            + grid[(index + 1) % cells] * amount
        ) * amplitude
        total += amplitude
        amplitude *= 0.5
    return np.asarray(result / total, dtype=np.float32)


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
    sky_noise = fbm(width, height, 5100, octaves=5, base=5)
    air = fbm(width, height, 5200, octaves=4, base=3)

    terrain_x = x[0]
    far_shape = _periodic_fbm_x(terrain_x, width, 5401, 5)
    mid_shape = _periodic_fbm_x(terrain_x, width, 5411, 8)
    near_shape = _periodic_fbm_x(terrain_x, width, 5421, 13, 3)
    far_ridge = height * (
        0.66 + (far_shape - 0.5) * 0.14 + np.sin(terrain_x * 0.0041 + 0.7) * 0.025
    )
    mid_ridge = height * (
        0.735 + (mid_shape - 0.5) * 0.13 + np.sin(terrain_x * 0.0073 + 2.1) * 0.018
    )
    near_ridge = height * (
        0.82 + (near_shape - 0.5) * 0.09 + np.sin(terrain_x * 0.012 + 0.4) * 0.012
    )

    stars = np.zeros((height, width, 3), dtype=np.float32)
    generator = np.random.default_rng(5301)
    star_colors = np.asarray(
        ((0.70, 0.82, 1.0), (1.0, 0.88, 0.70), (0.82, 0.91, 1.0)),
        dtype=np.float32,
    )
    for _ in range(680):
        star_x = int(generator.integers(8, width - 8))
        star_y = int(generator.integers(8, round(height * 0.62)))
        radius = float(generator.uniform(0.75, 2.25))
        extent = max(2, round(radius * 2.5))
        local_y, local_x = np.mgrid[-extent:extent + 1, -extent:extent + 1]
        glow = np.exp(-(local_x * local_x + local_y * local_y) / (radius * radius))
        intensity = float(generator.uniform(0.18, 0.82))
        color = star_colors[int(generator.integers(0, len(star_colors)))]
        stars[
            star_y - extent:star_y + extent + 1,
            star_x - extent:star_x + extent + 1,
        ] += glow[..., None] * intensity * color

    for name, (top, horizon, far_land, near_land) in AURORA_PALETTES.items():
        base = _gradient(top, horizon)
        base += (sky_noise[..., None] - 0.5) * 0.045
        haze = np.exp(-((y / height - 0.59) / 0.20) ** 2)
        cloud = np.clip((air - 0.46) * 0.28, 0.0, 0.11) * haze
        base = base * (1.0 - cloud[..., None]) + _color(horizon)[None, None, :] * cloud[..., None]
        base += stars * {"night": 0.82, "dawn": 0.12, "day": 0.0}[name]

        ridge_haze = np.exp(-((y - far_ridge[None, :]) / (height * 0.035)) ** 2)
        ridge_haze *= y < far_ridge[None, :]
        base = base * (1.0 - ridge_haze[..., None] * 0.12) \
            + _color(horizon)[None, None, :] * ridge_haze[..., None] * 0.12

        far_ground = y >= far_ridge[None, :]
        far_depth = np.clip((y - far_ridge[None, :]) / (height * 0.28), 0.0, 1.0)
        far_rgb = _color(far_land)[None, None, :] * (
            0.93 - far_depth[..., None] * 0.23
        )
        far_rgb *= 0.91 + sky_noise[..., None] * 0.09
        base[far_ground] = far_rgb[far_ground]

        mid_ground = y >= mid_ridge[None, :]
        mid_depth = np.clip((y - mid_ridge[None, :]) / (height * 0.22), 0.0, 1.0)
        mid_color = _color(far_land) * 0.30 + _color(near_land) * 0.70
        mid_rgb = mid_color[None, None, :] * (0.90 - mid_depth[..., None] * 0.22)
        mid_rgb *= 0.86 + air[..., None] * 0.14
        base[mid_ground] = mid_rgb[mid_ground]

        near_ground = y >= near_ridge[None, :]
        near_depth = np.clip((y - near_ridge[None, :]) / (height * 0.16), 0.0, 1.0)
        near_rgb = _color(near_land)[None, None, :] * (
            0.92 - near_depth[..., None] * 0.28
        )
        near_rgb *= 0.82 + sky_noise[..., None] * 0.18
        base[near_ground] = near_rgb[near_ground]
        save_rgba(out / f"aurora_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)

    padding = (width - AURORA_VIEW_WIDTH * 2) // 2
    period = width - padding * 2
    position = np.mod(terrain_x - padding, period)
    unit = position / period
    curtain_specs = (
        (0.155, 0.38, 0.72, 6101, 0.3, 0.10, 0.015),
        (0.205, 0.42, 0.86, 6201, 2.0, 0.13, 0.035),
        (0.255, 0.36, 0.76, 6301, 4.1, 0.15, 0.090),
    )
    green = _color((72, 211, 139))
    cyan = _color((69, 174, 184))
    violet = _color((137, 105, 170))
    for index, (crest_y, ray_length, strength, seed, phase, cyan_base, violet_base) in enumerate(curtain_specs):
        broad = _periodic_fbm_x(position, period, seed, 4)
        medium = _periodic_fbm_x(position, period, seed + 31, 11, 3)
        fine = _periodic_fbm_x(position, period, seed + 53, 29, 3)
        fold = (
            np.sin(unit * np.pi * 2.0 + phase) * 0.038
            + np.sin(unit * np.pi * 6.0 + phase * 0.7) * 0.025
            + np.sin(unit * np.pi * 14.0 - phase * 0.4) * 0.013
            + (broad - 0.5) * 0.075
        )
        crest = height * (crest_y + fold)[None, :]
        distance = y - crest
        positive = np.maximum(distance, 0.0)
        negative = np.maximum(-distance, 0.0)
        length = height * (
            ray_length + (broad - 0.5) * 0.13 + (medium - 0.5) * 0.055
        )[None, :]

        gate = np.clip((distance + height * 0.012) / (height * 0.035), 0.0, 1.0)
        gate = gate * gate * (3.0 - 2.0 * gate)
        ending = np.clip((length - positive) / (height * 0.10), 0.0, 1.0)
        ending = ending * ending * (3.0 - 2.0 * ending)
        cycles = 79 + index * 18
        thread_phase = (
            unit[None, :] * np.pi * 2.0 * cycles
            + (medium[None, :] - 0.5) * 8.0
            + distance * (0.0085 + index * 0.0012)
        )
        threads = (0.5 + 0.5 * np.cos(thread_phase)) ** 10
        fine_threads = (
            0.5
            + 0.5 * np.cos(
                unit[None, :] * np.pi * 2.0 * (cycles + 53)
                - (fine[None, :] - 0.5) * 10.0
                + distance * 0.005
                + 1.7
            )
        ) ** 14
        striation = 0.15 + threads * 0.51 + fine_threads * 0.34
        presence = np.clip((broad - 0.17) / 0.69, 0.0, 1.0)[None, :]
        fold_face = (
            0.38
            + 0.62 * (0.5 + 0.5 * np.sin(unit * np.pi * 10.0 + phase)) ** 2
        )[None, :]

        edge = np.exp(-(distance / (height * (0.017 + index * 0.002))) ** 2)
        lower_rays = gate * np.exp(-positive / (length * 0.70)) * ending * striation
        upper_rays = (1.0 - gate) * np.exp(-negative / (height * 0.085)) * striation
        veil = gate * np.exp(-positive / (length * 0.92)) * ending
        veil *= 0.35 + medium[None, :] * 0.65
        alpha = strength * presence * fold_face * (
            edge * 0.31 + lower_rays * 0.74 + upper_rays * 0.20 + veil * 0.12
        )
        alpha *= np.clip((height * 0.70 - y) / (height * 0.13), 0.0, 1.0)
        alpha = feather_alpha(np.asarray(np.clip(alpha, 0.0, 0.88), np.float32), padding, 48)

        ray_amount = np.clip(positive / np.maximum(length, 1.0), 0.0, 1.0)
        cyan_amount = np.clip(cyan_base + fine_threads * 0.08 + (1.0 - ray_amount) * 0.035, 0.0, 0.24)
        violet_amount = np.clip(
            violet_base * (0.25 + ray_amount * 0.75) * (0.45 + threads * 0.55),
            0.0,
            0.12,
        )
        green_amount = 1.0 - cyan_amount - violet_amount
        rgb = (
            green[None, None, :] * green_amount[..., None]
            + cyan[None, None, :] * cyan_amount[..., None]
            + violet[None, None, :] * violet_amount[..., None]
        )
        brightness = 0.78 + striation * 0.27 + edge * 0.13
        rgb *= brightness[..., None]
        # The runtime wraps this exact view-width span, so close its discrete seam.
        alpha[:, padding + period - 1] = alpha[:, padding]
        rgb[:, padding + period - 1] = rgb[:, padding]
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
