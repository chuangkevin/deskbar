"""Bake dimensional mountain-ridge and grounded firefly-meadow layers."""

from __future__ import annotations

import argparse
import math
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
    "night": {
        "top": (8, 15, 34),
        "sky_horizon": (25, 42, 78),
        "horizon_glow": (160, 115, 65),
        "meadow_far": (15, 32, 35),
        "meadow_near": (10, 24, 22),
        "meadow_highlight": (25, 52, 40),
    },
    "dawn": {
        "top": (48, 34, 66),
        "sky_horizon": (185, 96, 115),
        "horizon_glow": (248, 175, 105),
        "meadow_far": (54, 38, 56),
        "meadow_near": (35, 48, 34),
        "meadow_highlight": (110, 105, 65),
    },
    "day": {
        "top": (86, 134, 166),
        "sky_horizon": (180, 196, 202),
        "horizon_glow": (225, 218, 185),
        "meadow_far": (108, 135, 98),
        "meadow_near": (52, 84, 46),
        "meadow_highlight": (145, 160, 105),
    },
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


def _meadow_vegetation_alpha(edge: float, seed: int, near: bool) -> FloatArray:
    """Rasterize deterministic organic meadow foliage into an alpha mask."""
    width, height = WORK_SIZE
    generator = np.random.default_rng(seed)
    surface = pygame.Surface(WORK_SIZE, pygame.SRCALPHA)

    # 1. Base rolling hill contour profile
    profile_noise = fbm(width, 8, seed + 10, octaves=4, base=6).mean(axis=0)
    profile = height * (edge + (profile_noise - 0.5) * (0.04 if near else 0.025))
    profile += np.sin(np.arange(width, dtype=np.float32) * 0.005 + seed) * height * 0.008

    # Ground base contour
    points = [(0, height - 1)]
    points.extend((x, round(float(profile[min(width - 1, max(0, x))]))) for x in range(0, width, 12))
    points.extend(((width - 1, round(float(profile[-1]))), (width - 1, height - 1)))
    pygame.draw.polygon(surface, (255, 255, 255, 230 if near else 210), points)

    # 2. Organic Grass Tufts with Bezier-curved tapered blades
    spacing = 10 if near else 14
    for base_x in range(-30, width + 30, spacing):
        cx = base_x + int(generator.integers(-spacing // 2, spacing // 2 + 1))
        gx = min(width - 1, max(0, cx))
        cy = float(profile[gx]) + float(generator.uniform(-8.0, 16.0))
        num_blades = int(generator.integers(8, 20 if near else 14))

        for _ in range(num_blades):
            bx = cx + float(generator.normal(0, 14 if near else 9))
            by = cy + float(generator.normal(0, 5))
            blade_h = float(generator.uniform(50 if near else 28, 160 if near else 85))
            curve_mid = float(generator.uniform(-30 if near else -18, 30 if near else 18))
            curve_tip = curve_mid + float(generator.uniform(-20 if near else -12, 20 if near else 12))

            p0 = (bx, by)
            p1 = (bx + curve_mid, by - blade_h * 0.5)
            p2 = (bx + curve_tip, by - blade_h)

            w_base = float(generator.uniform(3.0, 6.0) if near else generator.uniform(2.0, 3.8))
            ts = np.linspace(0.0, 1.0, 7)
            curve_pts = [
                ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
                for t in ts
            ]

            poly_left = []
            poly_right = []
            for i, (px, py) in enumerate(curve_pts):
                t = ts[i]
                w = w_base * (1.0 - t * 0.85)
                if i < len(curve_pts) - 1:
                    nx, ny = curve_pts[i + 1][0] - px, curve_pts[i + 1][1] - py
                else:
                    nx, ny = px - curve_pts[i - 1][0], py - curve_pts[i - 1][1]
                length = max(1e-4, math.hypot(nx, ny))
                dx, dy = -ny / length * (w * 0.5), nx / length * (w * 0.5)
                poly_left.append((px + dx, py + dy))
                poly_right.append((px - dx, py - dy))

            blade_poly = poly_left + poly_right[::-1]
            opacity = int(generator.integers(180, 255))
            pygame.draw.polygon(surface, (255, 255, 255, opacity), blade_poly)

    # 3. Wild Stalks & Grain Spikes (野穗草)
    num_stalks = 40 if near else 24
    for _ in range(num_stalks):
        sx = float(generator.uniform(-20, width + 20))
        gx = int(np.clip(sx, 0, width - 1))
        sy = float(profile[gx]) + float(generator.uniform(0, 12))
        sh = float(generator.uniform(130 if near else 70, 240 if near else 130))
        sbend = float(generator.uniform(-28, 28))

        tip_x, tip_y = sx + sbend, sy - sh
        mid_x, mid_y = sx + sbend * 0.4, sy - sh * 0.5
        opacity = int(generator.integers(190, 255))
        pygame.draw.lines(
            surface,
            (255, 255, 255, opacity),
            False,
            ((sx, sy), (mid_x, mid_y), (tip_x, tip_y)),
            3 if near else 2,
        )

        num_seeds = int(generator.integers(6, 13))
        for i in range(num_seeds):
            st = i / max(1, num_seeds - 1)
            seed_x = mid_x + (tip_x - mid_x) * st + float(generator.uniform(-5, 5))
            seed_y = mid_y + (tip_y - mid_y) * st
            radius = float(generator.uniform(3, 6.5) if near else generator.uniform(2, 3.8))
            pygame.draw.circle(
                surface,
                (255, 255, 255, opacity),
                (round(seed_x), round(seed_y)),
                round(radius),
            )

    # 4. Broad Leaves & Foliage Occlusion (枝葉遮蔽)
    if near:
        leaf_clusters = (
            (float(generator.uniform(0, 450)), 0.50, 0.70),
            (float(generator.uniform(width - 450, width)), 0.50, 0.70),
            (float(generator.uniform(400, width - 400)), 0.72, 0.86),
            (float(generator.uniform(150, width - 150)), 0.78, 0.90),
        )
        for cx_base, y_min, y_max in leaf_clusters:
            num_leaves = int(generator.integers(12, 28))
            for _ in range(num_leaves):
                lx = cx_base + float(generator.normal(0, 90))
                ly = height * float(generator.uniform(y_min, y_max))
                lw = float(generator.uniform(24, 60))
                lh = float(generator.uniform(12, 32))
                angle = float(generator.uniform(-65, 65))

                leaf_surf = pygame.Surface((round(lw * 2), round(lh * 2)), pygame.SRCALPHA)
                pygame.draw.ellipse(
                    leaf_surf,
                    (255, 255, 255, int(generator.integers(200, 255))),
                    (round(lw * 0.5), round(lh * 0.5), round(lw), round(lh)),
                )
                rotated = pygame.transform.rotate(leaf_surf, angle)
                surface.blit(
                    rotated,
                    (round(lx - rotated.get_width() / 2), round(ly - rotated.get_height() / 2)),
                )

    # 5. Ground Particles & Painterly Micro-Strokes (地面粒子/筆觸)
    if near:
        for _ in range(300):
            px = float(generator.uniform(0, width))
            py = float(generator.uniform(height * 0.72, height))
            sw = float(generator.uniform(10, 32))
            sh = float(generator.uniform(3, 7))
            opacity = int(generator.integers(120, 230))
            pygame.draw.ellipse(surface, (255, 255, 255, opacity), (px, py, sw, sh))

    alpha = np.asarray(pygame.surfarray.array_alpha(surface).T / 255.0, dtype=np.float32)
    return alpha


def generate_firefly_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    noise = fbm(width, height, 3100, octaves=5, base=7)
    fine = fbm(width, height, 3121, octaves=3, base=22)

    # 1. Base Layer for Night, Dawn, Day
    for name, palette in MEADOW_PALETTES.items():
        base = _gradient(palette["top"], palette["sky_horizon"])
        cloud = fbm(width, height, 3160, octaves=4, base=4)
        cloud_band = np.exp(-((y - height * 0.32) / (height * 0.22)) ** 2)
        base += (cloud[..., None] - 0.5) * cloud_band[..., None] * 0.08

        # Background rolling hill profile
        hill_profile = fbm(width, 6, 3142, octaves=4, base=5).mean(axis=0)
        meadow_edge = height * (
            0.62
            + np.sin(x * 0.005) * 0.015
            + (hill_profile[None, :] - 0.5) * 0.045
        )
        ground = y >= meadow_edge

        relief = noise - np.roll(noise, shift=(7, -10), axis=(0, 1))
        meadow_rgb = _color(palette["meadow_near"])[None, None, :] * (
            0.55 + noise[..., None] * 0.45 + relief[..., None] * 0.30
        )
        meadow_rgb += (fine[..., None] - 0.5) * 0.06

        if name == "day":
            # Distinct daylight grass and soil texture
            soil_mask = np.clip((fbm(width, height, 3180, octaves=4, base=12) - 0.48) * 2.2, 0.0, 1.0)
            soil_color = _color((88, 76, 52))[None, None, :]
            meadow_rgb = meadow_rgb * (1.0 - soil_mask[..., None] * 0.35) + soil_color * (soil_mask[..., None] * 0.35)

        distance_into_ground = np.clip((y - meadow_edge) / (height * 0.36), 0.0, 1.0)
        meadow_rgb *= 1.0 - distance_into_ground[..., None] * 0.25
        base[ground] = meadow_rgb[ground]

        horizon_light = np.exp(-((y - height * 0.54) / (height * 0.16)) ** 2)
        glow_intensity = 0.08 if name == "night" else (0.22 if name == "dawn" else 0.12)
        base += horizon_light[..., None] * _color(palette["horizon_glow"])[None, None, :] * glow_intensity

        stem_texture = np.clip(
            np.sin(x * 0.14 + fine * 7.0) * 0.5 + 0.5 - distance_into_ground * 0.60,
            0.0,
            1.0,
        )
        base[ground] += stem_texture[ground, None] * _color(palette["meadow_highlight"])[None, :] * 0.15
        save_rgba(out / f"fireflies_base_{name}.png", _rgba(base, np.ones((height, width), np.float32)), False)

    # 2. Vegetation Layers: Far & Near Grass
    for layer, edge, seed, color, is_near in (
        ("far", 0.64, 3210, (52, 78, 48), False),
        ("near", 0.74, 3320, (28, 56, 36), True),
    ):
        grass_noise = fbm(width, height, seed, octaves=4, base=15)
        alpha = _meadow_vegetation_alpha(edge, seed, is_near)
        alpha = feather_alpha(alpha, 32, 16)

        rgb = np.broadcast_to(_color(color), (height, width, 3)).copy()
        grass_relief = grass_noise - np.roll(grass_noise, shift=(4, -6), axis=(0, 1))
        rgb *= 0.58 + grass_noise[..., None] * 0.44 + grass_relief[..., None] * 0.26

        # Rim light highlight on foliage tips vs ambient shadow at ground base
        tip_light = np.clip((height * edge - y) / (height * 0.25), 0.0, 1.0)[..., None]
        highlight_color = _color((138, 142, 65) if is_near else (115, 125, 75))[None, None, :]
        shadow_color = _color((12, 24, 18) if is_near else (20, 32, 28))[None, None, :]
        rgb = rgb * (1.0 + tip_light * 0.35) + highlight_color * (tip_light * 0.25)
        ground_shadow = np.clip((y - height * edge) / (height * 0.25), 0.0, 1.0)[..., None]
        rgb = rgb * (1.0 - ground_shadow * 0.30) + shadow_color * (ground_shadow * 0.15)

        save_rgba(out / f"fireflies_grass_{layer}.png", _rgba(rgb, alpha), True)

    # 3. Haze Layer
    haze_shape = np.exp(-((y - height * 0.58) / (height * 0.11)) ** 2)
    haze_alpha = haze_shape * np.clip(0.04 + noise * 0.26 + (fine - 0.5) * 0.08, 0.0, 0.32)
    haze_alpha = feather_alpha(np.asarray(haze_alpha, np.float32), 96, 32)
    haze_rgb = np.broadcast_to(_color((220, 195, 155)), (height, width, 3)).copy()
    haze_rgb *= 0.88 + fine[..., None] * 0.12
    save_rgba(out / "fireflies_haze.png", _rgba(haze_rgb, haze_alpha), True)

    # 4. Glow Layers (glow_0: far fireflies, glow_1: near fireflies)
    cx, cy = width * 0.5, height * 0.5
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    angle = np.arctan2(y - cy, x - cx)

    # glow_0: far firefly (smaller, 2-layer subtle halo)
    core_0 = np.exp(-(distance / 5.5) ** 2)
    inner_0 = np.exp(-(distance / 15.0) ** 2) * 0.65
    outer_0 = np.exp(-(distance / 30.0) ** 2) * 0.28
    # The runtime crops a small sprite out of this wide asset.  Fade by radial
    # distance—not square distance—so the crop stays fully transparent at its
    # corners and the halo remains circular on every compositor.
    fade_0 = np.clip((26.0 - distance) / (26.0 - 16.0), 0.0, 1.0)
    fade_0 = fade_0 * fade_0 * (3.0 - 2.0 * fade_0)
    alpha_0 = feather_alpha(np.asarray(np.clip((core_0 + inner_0 + outer_0) * fade_0, 0.0, 1.0), np.float32), 16, 16)
    c_core_0 = _color((245, 255, 205))
    c_inner_0 = _color((200, 235, 90))
    c_outer_0 = _color((235, 200, 70))
    w_c0, w_i0, w_o0 = core_0[..., None], inner_0[..., None], outer_0[..., None]
    rgb_0 = (c_core_0 * w_c0 + c_inner_0 * w_i0 + c_outer_0 * w_o0) / (w_c0 + w_i0 + w_o0 + 1e-6)
    save_rgba(out / "fireflies_glow_0.png", _rgba(rgb_0, alpha_0), True)

    # glow_1: near firefly (larger, 2-layer halo with soft aura)
    core_1 = np.exp(-(distance / 9.0) ** 2)
    inner_1 = np.exp(-(distance / 24.0) ** 2) * 0.72
    outer_1 = np.exp(-(distance / 50.0) ** 2) * 0.35 * (1.0 + 0.08 * np.sin(angle * 6.0 + distance * 0.05))
    fade_1 = np.clip((48.0 - distance) / (48.0 - 30.0), 0.0, 1.0)
    fade_1 = fade_1 * fade_1 * (3.0 - 2.0 * fade_1)
    alpha_1 = feather_alpha(np.asarray(np.clip((core_1 + inner_1 + outer_1) * fade_1, 0.0, 1.0), np.float32), 16, 16)
    c_core_1 = _color((250, 255, 215))
    c_inner_1 = _color((210, 245, 95))
    c_outer_1 = _color((245, 195, 75))
    w_c1, w_i1, w_o1 = core_1[..., None], inner_1[..., None], outer_1[..., None]
    rgb_1 = (c_core_1 * w_c1 + c_inner_1 * w_i1 + c_outer_1 * w_o1) / (w_c1 + w_i1 + w_o1 + 1e-6)
    save_rgba(out / "fireflies_glow_1.png", _rgba(rgb_1, alpha_1), True)


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
