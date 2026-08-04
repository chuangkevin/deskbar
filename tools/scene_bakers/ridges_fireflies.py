"""Bake dimensional mountain-ridge and grounded firefly-meadow layers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import numpy as np
import pygame
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


def _angular_noise(width: int, seed: int, spacing: int) -> FloatArray:
    """Interpolate sparse deterministic anchors without rounding their corners."""
    generator = np.random.default_rng(seed)
    anchors = np.arange(-spacing, width + spacing * 2, spacing, dtype=np.float32)
    values = generator.uniform(-1.0, 1.0, anchors.size).astype(np.float32)
    return np.asarray(
        np.interp(np.arange(width, dtype=np.float32), anchors, values),
        dtype=np.float32,
    )


def _mountain_profile(
    width: int,
    height: int,
    base_y: float,
    rise: float,
    spacing: int,
    seed: int,
) -> FloatArray:
    """Build overlapping angular ranges at major, secondary, and crag scales."""
    baseline = height * (
        base_y
        + _angular_noise(width, seed + 1, spacing) * 0.015
        + _angular_noise(width, seed + 2, max(32, spacing // 3)) * 0.006
    )
    profile = baseline.copy()

    def add_peaks(peak_spacing: int, peak_rise: float, peak_seed: int) -> None:
        generator = np.random.default_rng(peak_seed)
        center = -peak_spacing // 2 + int(generator.integers(0, peak_spacing // 2))
        while center < width + peak_spacing:
            left = peak_spacing * float(generator.uniform(1.02, 1.52))
            right = peak_spacing * float(generator.uniform(1.02, 1.52))
            summit_x = min(width - 1, max(0, center))
            summit = baseline[summit_x] - height * peak_rise * float(
                generator.uniform(0.58, 1.18)
            )
            start = max(0, round(center - left))
            stop = min(width, round(center + right) + 1)
            sample_x = np.arange(start, stop, dtype=np.float32)
            distance = np.where(
                sample_x <= center,
                (center - sample_x) / left,
                (sample_x - center) / right,
            )
            candidate = summit + (baseline[start:stop] - summit) * distance
            profile[start:stop] = np.minimum(profile[start:stop], candidate)
            center += round(peak_spacing * float(generator.uniform(0.78, 1.24)))

    add_peaks(spacing, rise, seed + 10)
    add_peaks(max(100, round(spacing * 0.58)), rise * 0.28, seed + 20)
    profile += height * (
        _angular_noise(width, seed + 30, max(24, spacing // 5)) * 0.014
        + _angular_noise(width, seed + 31, max(14, spacing // 11)) * 0.006
        + _angular_noise(width, seed + 32, max(8, spacing // 29)) * 0.0025
    )
    return np.asarray(np.clip(profile, height * 0.14, height * 0.88), dtype=np.float32)


def _drainage_field(
    x: FloatArray,
    y: FloatArray,
    width: int,
    height: int,
    seed: int,
    direction: float,
) -> FloatArray:
    """Shear sparse irregular channel seeds into descending rock gullies."""
    generator = np.random.default_rng(seed)
    sample_x = np.arange(width, dtype=np.float32)
    channels = np.zeros(width, dtype=np.float32)
    center = float(generator.uniform(-80.0, 40.0))
    while center < width + 80:
        radius = float(generator.uniform(2.2, 5.8))
        strength = float(generator.uniform(0.48, 1.0))
        channels = np.maximum(
            channels,
            np.exp(-(((sample_x - center) / radius) ** 2)) * strength,
        )
        center += float(generator.uniform(92.0, 188.0))
    bend = np.sin(y / (height * 0.075) + seed) * height * 0.008
    indices = np.mod(np.rint(x - y * direction - bend).astype(np.int32), width)
    drainage = channels[indices]

    branches = np.zeros(width, dtype=np.float32)
    for center in generator.uniform(0.0, width, max(5, width // 430)):
        radius = float(generator.uniform(1.8, 4.2))
        branches = np.maximum(
            branches,
            np.exp(-(((sample_x - center) / radius) ** 2))
            * float(generator.uniform(0.35, 0.70)),
        )
    branch_bend = np.sin(y / (height * 0.052) + seed * 0.7) * height * 0.006
    branch_indices = np.mod(
        np.rint(x + y * direction * 0.65 - branch_bend).astype(np.int32),
        width,
    )
    branch_gate = np.clip(
        np.sin(y / (height * 0.045) + seed * 0.3) * 2.0,
        0.0,
        1.0,
    )
    return np.asarray(np.maximum(drainage, branches[branch_indices] * branch_gate), dtype=np.float32)


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
        ("far", 0.55, 0.29, 400, 2301, 0.66, 0.43, 0.30, 0.18),
        ("mid", 0.68, 0.27, 470, 2402, 0.53, 0.51, 0.22, -0.14),
        ("near", 0.81, 0.23, 560, 2503, 0.39, 0.61, 0.10, 0.20),
    )
    for (
        name,
        base_y,
        rise,
        peak_spacing,
        seed,
        luminance_floor,
        snow_line,
        snow_strength,
        drainage_direction,
    ) in specifications:
        profile = _mountain_profile(width, height, base_y, rise, peak_spacing, seed)
        depth = y - profile[None, :]
        alpha = feather_alpha(
            np.asarray(np.clip(depth / 2.5, 0.0, 1.0), np.float32),
            6,
            3,
        )
        texture = fbm(width, height, seed + 40, octaves=5, base=9)
        fine = fbm(width, height, seed + 41, octaves=4, base=23)
        relief = texture - np.roll(texture, shift=(9, -15), axis=(0, 1))
        upper_face = np.exp(-np.clip(depth, 0.0, None) / (height * 0.28))
        facets = np.tanh(np.gradient(profile) * 0.36)[None, :] * upper_face
        facets *= 0.72 + texture * 0.28
        drainage = _drainage_field(
            x,
            y,
            width,
            height,
            seed + 50,
            drainage_direction,
        )
        drainage *= np.clip(depth / (height * 0.025), 0.0, 1.0)
        drainage *= np.clip(1.0 - depth / (height * 0.48), 0.0, 1.0)
        strata = np.sin(x * 0.025 - y * 0.043 + fine * 5.0)
        luminance = np.clip(
            luminance_floor
            + (texture - 0.5) * 0.22
            + relief * 0.82
            + facets * 0.085
            + strata * upper_face * 0.035
            - drainage * 0.075
            + np.clip(1.0 - depth / (height * 0.055), 0.0, 1.0) * 0.10
            - np.clip(depth / height, 0.0, 1.0) * 0.18,
            0.12,
            1.0,
        )
        elevation = np.clip(
            (height * snow_line - profile) / (height * 0.16),
            0.0,
            1.0,
        )[None, :]
        snow_depth = height * (0.025 + elevation * 0.07)
        snow_cap = elevation * np.clip(1.0 - depth / snow_depth, 0.0, 1.0)
        snow_patch = np.clip((fine - 0.38) * 2.4 + relief * 0.8, 0.0, 1.0)
        snow = snow_cap * (0.28 + snow_patch * 0.72) * (1.0 - drainage * 0.65)
        luminance = np.clip(luminance + snow * snow_strength, 0.12, 1.0)
        rgb = np.repeat(luminance[..., None], 3, axis=2)
        save_rgba(out / f"ridges_{name}.png", _rgba(rgb, alpha), True)

    # The 224-work-pixel period matches runtime's 112-output-pixel wrap.
    fog_texture = np.zeros((height, width), dtype=np.float32)
    generator = np.random.default_rng(2704)
    for harmonic, strength in ((1, 0.42), (2, 0.25), (3, 0.17), (5, 0.10), (7, 0.06)):
        phase = float(generator.uniform(0.0, np.pi * 2.0))
        vertical = float(generator.uniform(1.1, 3.8))
        fog_texture += np.sin(
            np.pi * 2.0 * (harmonic * x / 224.0 + y / (height * vertical)) + phase
        ) * strength
    fog_texture = np.clip(fog_texture * 0.46 + 0.5, 0.0, 1.0)
    fog_bands = (
        np.exp(-((y - height * 0.48) / (height * 0.055)) ** 2) * 0.54
        + np.exp(-((y - height * 0.60) / (height * 0.075)) ** 2) * 0.86
        + np.exp(-((y - height * 0.71) / (height * 0.095)) ** 2) * 0.42
    )
    fog_alpha = np.clip(fog_bands * (0.09 + fog_texture * 0.48), 0.0, 0.55)
    fog_alpha = feather_alpha(np.asarray(fog_alpha, np.float32), 4, 18)
    fog_rgb = np.broadcast_to(_color((218, 229, 234)), (height, width, 3)).copy()
    fog_rgb *= 0.94 + fog_texture[..., None] * 0.06
    save_rgba(out / "ridges_fog.png", _rgba(fog_rgb, fog_alpha), True)
    shadow_noise = fbm(width, height, 2805, octaves=5, base=6)
    shadow_alpha = np.exp(-((y - height * 0.68) / (height * 0.20)) ** 2)
    shadow_alpha *= np.clip((shadow_noise - 0.35) * 0.82, 0.0, 0.36)
    shadow_alpha = feather_alpha(np.asarray(shadow_alpha, np.float32), 48, 24)
    shadow_rgb = np.zeros((height, width, 3), dtype=np.float32)
    save_rgba(out / "ridges_shadow.png", _rgba(shadow_rgb, shadow_alpha), True)


def _grass_alpha(edge: float, seed: int, near: bool) -> FloatArray:
    """Rasterize deterministic curved blades into a dense, irregular meadow edge."""
    width, height = WORK_SIZE
    generator = np.random.default_rng(seed)
    mask = pygame.Surface(WORK_SIZE, pygame.SRCALPHA)
    profile_noise = fbm(width, 6, seed + 9, octaves=4, base=5).mean(axis=0)
    profile = height * (edge + (profile_noise - 0.5) * (0.035 if near else 0.025))
    profile += np.sin(np.arange(width, dtype=np.float32) * 0.006 + seed) * height * 0.008
    points = [(0, height - 1)]
    points.extend((x, round(float(profile[x]))) for x in range(0, width, 8))
    points.extend(((width - 1, round(float(profile[-1]))), (width - 1, height - 1)))
    pygame.draw.polygon(mask, (255, 255, 255, 248), points)

    spacing = 5 if near else 8
    for base_x in range(-40, width + 40, spacing):
        x = base_x + int(generator.integers(-spacing // 2, spacing // 2 + 1))
        base_y = int(profile[min(width - 1, max(0, x))]) + int(generator.integers(0, 13))
        blade_height = int(generator.integers(30 if near else 18, 94 if near else 57))
        bend = int(generator.integers(-19 if near else -11, 20 if near else 12))
        tip = (x + bend, base_y - blade_height)
        middle = (x + bend // 3, base_y - blade_height * 3 // 5)
        opacity = int(generator.integers(190, 256))
        pygame.draw.lines(
            mask,
            (255, 255, 255, opacity),
            False,
            ((x, base_y + 7), middle, tip),
            3 if near and base_x % 3 == 0 else 2,
        )
        if base_x % (spacing * 5) == 0:
            side = -1 if (base_x // spacing) % 2 else 1
            branch_y = base_y - blade_height // 2
            pygame.draw.line(mask, (255, 255, 255, opacity - 30),
                             (x + bend // 4, branch_y),
                             (x + bend // 4 + side * (12 if near else 8), branch_y - 9), 2)
        if not near and base_x % (spacing * 11) == 0:
            pygame.draw.line(mask, (255, 255, 255, 175), tip,
                             (tip[0] + (3 if bend >= 0 else -3), tip[1] - 8), 3)
    return np.asarray(pygame.surfarray.array_alpha(mask).T / 255.0, dtype=np.float32)


def generate_firefly_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 3100, octaves=5, base=7)
    fine = fbm(width, height, 3121, octaves=3, base=22)
    horizon_profile = fbm(width, 6, 3142, octaves=4, base=5).mean(axis=0)
    for name, (top, horizon, meadow) in MEADOW_PALETTES.items():
        base = _gradient(top, horizon)
        cloud = fbm(width, height, 3160, octaves=4, base=4)
        cloud_band = np.exp(-((y - height * 0.31) / (height * 0.21)) ** 2)
        base += (cloud[..., None] - 0.5) * cloud_band[..., None] * 0.075
        meadow_edge = height * (
            0.665
            + np.sin(x * 0.0067) * 0.012
            + (horizon_profile[None, :] - 0.5) * 0.055
        )
        ground = y >= meadow_edge
        relief = noise - np.roll(noise, shift=(7, -10), axis=(0, 1))
        meadow_rgb = _color(meadow)[None, None, :] * (
            0.53 + noise[..., None] * 0.47 + relief[..., None] * 0.32
        )
        meadow_rgb += (fine[..., None] - 0.5) * 0.055
        distance_into_ground = np.clip((y - meadow_edge) / (height * 0.34), 0.0, 1.0)
        meadow_rgb *= 1.0 - distance_into_ground[..., None] * 0.23
        base[ground] = meadow_rgb[ground]
        horizon_light = np.exp(-((y - height * 0.57) / (height * 0.16)) ** 2)
        base += horizon_light[..., None] * _color((235, 185, 109))[None, None, :] \
            * (0.075 if name == "night" else 0.13)
        stem_texture = np.clip(
            np.sin(x * 0.16 + fine * 8.0) * 0.5 + 0.5 - distance_into_ground * 0.65,
            0.0,
            1.0,
        )
        base[ground] += stem_texture[ground, None] * 0.025
        save_rgba(out / f"fireflies_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)
    for layer, edge, seed, color, is_near in (
        ("far", 0.685, 3210, (88, 107, 68), False),
        ("near", 0.79, 3320, (27, 54, 36), True),
    ):
        grass_noise = fbm(width, height, seed, octaves=4, base=15)
        alpha = _grass_alpha(edge, seed, is_near)
        alpha = feather_alpha(alpha, 5, 3)
        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        grass_relief = grass_noise - np.roll(grass_noise, shift=(4, -6), axis=(0, 1))
        rgb *= 0.57 + grass_noise[..., None] * 0.46 + grass_relief[..., None] * 0.28
        rgb += np.clip((height * edge - y) / (height * 0.14), 0.0, 1.0)[..., None] \
            * _color((104, 91, 47))[None, None, :] * 0.09
        save_rgba(out / f"fireflies_grass_{layer}.png", _rgba(rgb, alpha), True)
    haze_shape = np.exp(-((y - height * 0.61) / (height * 0.105)) ** 2)
    haze_alpha = haze_shape * np.clip(0.04 + noise * 0.20 + (fine - 0.5) * 0.08, 0.0, 0.30)
    haze_alpha = feather_alpha(np.asarray(haze_alpha, np.float32), 72, 24)
    haze_rgb = np.broadcast_to(_color((218, 190, 144)), (height, width, 3)).copy()
    haze_rgb *= 0.88 + fine[..., None] * 0.12
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
