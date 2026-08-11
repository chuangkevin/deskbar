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
    "night": ((14, 23, 38), (38, 54, 76), (82, 115, 138)),
    "dawn": ((62, 48, 62), (148, 115, 110), (192, 142, 120)),
    "day": ((206, 204, 188), (238, 230, 206), (115, 146, 150)),
}
INK_PAPER_PALETTES: Final = {
    "night": ((14, 19, 29), (42, 48, 59), (69, 82, 98)),
    "dawn": ((73, 56, 65), (154, 128, 111), (112, 73, 82)),
    "day": ((211, 207, 188), (242, 231, 201), (97, 108, 117)),
}


def _color(rgb: tuple[int, int, int]) -> FloatArray:
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _rgba(rgb: FloatArray, alpha: FloatArray) -> FloatArray:
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha[..., None]), axis=2)


def _smoothstep(values: FloatArray) -> FloatArray:
    clipped = np.clip(values, 0.0, 1.0)
    return np.asarray(clipped * clipped * (3.0 - 2.0 * clipped), dtype=np.float32)


def _ink_paper(
    mode: str,
    noise: FloatArray,
    seed: int,
) -> FloatArray:
    """Build horizontal sumi-e landscape banner on Xuan paper with 3 distinct depth zones.

    Features:
    - Far: Soft mountain ridges veiled in mist.
    - Mid: Winding river stream, wet ink washes, and organic ink channels.
    - Near: Foreground shoreline, wet-on-wet paper wash, moss green / cinnabar point accents.
    - Xuan paper texture: fine/medium fibers, dry-brush grain, and ink drying edge deposition.
    - Organized left-to-right spatial rhythm across the 1240x472 banner.
    """
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)

    # Multi-scale domain warping and noise fields
    warp_x = fbm(width, height, seed + 11, octaves=4, base=5)
    warp_y = fbm(width, height, seed + 23, octaves=4, base=5)
    fine = fbm(width, height, seed + 37, octaves=5, base=22)
    mid_noise = fbm(width, height, seed + 71, octaves=4, base=11)
    stroke_noise = fbm(width, height, seed + 103, octaves=4, base=16)

    # 1. Color Palettes according to mode (Night / Dawn / Day)
    if mode == "night":
        # Night: Deep indigo ink & moon-white wet paper / river light
        c_paper_bg = _color((14, 20, 32))
        c_paper_wash = _color((26, 36, 54))
        c_far_mist = _color((44, 62, 90))
        c_mid_ink = _color((8, 12, 22))
        c_river_light = _color((60, 88, 122))  # Moon-white wet wash
        c_accent = _color((135, 168, 205))     # Moonlit paper luster
    elif mode == "dawn":
        # Dawn: Smoky pink, warm gray, pale gold
        c_paper_bg = _color((52, 40, 48))
        c_paper_wash = _color((118, 94, 92))
        c_far_mist = _color((162, 122, 118))
        c_mid_ink = _color((46, 32, 38))
        c_river_light = _color((192, 148, 118))  # Pale gold light
        c_accent = _color((182, 120, 130))      # Smoky rose accent
    else:  # day
        # Day: Rice-white xuan paper, moss green, minimal cinnabar
        c_paper_bg = _color((232, 226, 210))    # Rice-white paper
        c_paper_wash = _color((245, 241, 228))  # Luminous paper wash
        c_far_mist = _color((138, 162, 155))    # Soft pale mist
        c_mid_ink = _color((26, 34, 32))        # Deep sumi-e ink
        c_river_light = _color((72, 128, 96))    # Moss green stream wash
        c_accent = _color((215, 42, 30))        # Minimal organic cinnabar red

    # Base Xuan Paper Gradient & Subtle Wash
    grad = np.clip(y / height + (noise - 0.5) * 0.06, 0.0, 1.0)[..., None]
    rgb = c_paper_bg[None, None, :] + (c_paper_wash - c_paper_bg)[None, None, :] * grad

    # -------------------------------------------------------------------------
    # DEPTH LAYER 1 (Far / 遠景): Layered Mountain Silhouettes & Horizon Mist
    # -------------------------------------------------------------------------
    # Peak 1 (Left to Center-Right mountain range)
    r1_y = height * (0.16 + 0.14 * np.sin(x * 0.0022 + warp_x * 2.2)) + (warp_y - 0.5) * height * 0.06
    r1_mask = _smoothstep((y - r1_y) / (height * 0.18)) * _smoothstep((height * 0.58 - y) / (height * 0.30))

    # Peak 2 (Right distant peaks)
    r2_y = height * (0.26 + 0.16 * np.cos(x * 0.0032 + seed * 0.1 + warp_y * 2.0)) + (warp_x - 0.5) * height * 0.05
    r2_mask = _smoothstep((y - r2_y) / (height * 0.20)) * _smoothstep((height * 0.68 - y) / (height * 0.32))

    far_mountains = np.clip(r1_mask * 0.70 + r2_mask * 0.60, 0.0, 1.0)[..., None]
    rgb += far_mountains * c_far_mist[None, None, :] * 0.32

    # -------------------------------------------------------------------------
    # DEPTH LAYER 2 (Mid / 中景): Winding River Stream & Ink Shores (左高右低空間節奏)
    # -------------------------------------------------------------------------
    # Left Promontory Mass (x: 0.0 .. 0.50)
    hill_left_profile = height * (0.28 + 0.32 * (x / width) ** 0.8 + (warp_x - 0.5) * 0.12)
    hill_left = _smoothstep((y - hill_left_profile) / (height * 0.16)) * (1.0 - _smoothstep((x - width * 0.52) / (width * 0.22)))

    # Right Island Promontory (x: 0.58 .. 1.0)
    hill_right_profile = height * (0.32 + 0.28 * ((width - x) / width) ** 0.85 + (warp_y - 0.5) * 0.10)
    hill_right = _smoothstep((y - hill_right_profile) / (height * 0.18)) * _smoothstep((x - width * 0.42) / (width * 0.25))

    mid_land_mask = np.clip(hill_left * 0.88 + hill_right * 0.78, 0.0, 1.0)

    # Dry-brush gaps & wet ink fissures
    fissure = np.clip(1.0 - np.abs(mid_noise - 0.48) * 3.0, 0.0, 1.0)
    ink_density = np.clip(mid_land_mask * (0.50 + fissure * 0.50) * (0.82 + fine * 0.18), 0.0, 1.0)[..., None]
    rgb = rgb * (1.0 - ink_density * 0.55) + c_mid_ink[None, None, :] * (ink_density * 0.55)

    # Winding River Stream Channel (溪流)
    stream_y = height * (0.64 + 0.10 * np.sin(x * 0.0030 + warp_x * 2.0) - 0.08 * (x / width))
    stream_dist = np.abs(y - stream_y) / (height * 0.15)
    stream_mask = np.exp(-(stream_dist ** 2)) * (0.45 + 0.55 * np.sin(x * 0.007 + stroke_noise * 3.5) * 0.5 + 0.5)
    stream_mask = np.clip(stream_mask * (0.75 + fine * 0.25), 0.0, 1.0)[..., None]
    rgb += stream_mask * c_river_light[None, None, :] * 0.35

    # -------------------------------------------------------------------------
    # DEPTH LAYER 3 (Near / 近景): Horizontal Mist Bands & Wet Wash Accents
    # -------------------------------------------------------------------------
    # Mist Bands floating across mountains & stream
    mist_top = np.exp(-((y - height * 0.22 - (warp_x - 0.5) * 35.0) / (height * 0.07)) ** 2)
    mist_mid = np.exp(-((y - height * 0.50 - (warp_y - 0.5) * 45.0) / (height * 0.09)) ** 2) * (0.35 + 0.65 * np.sin(x * 0.003 + 1.0))
    mist_bot = np.exp(-((y - height * 0.80 - (warp_x - 0.5) * 30.0) / (height * 0.08)) ** 2)
    mist_layer = np.clip(mist_top * 0.35 + mist_mid * 0.45 + mist_bot * 0.30, 0.0, 1.0)[..., None]

    # Blend mist into background
    if mode == "day":
        rgb = rgb * (1.0 - mist_layer * 0.25) + c_paper_wash[None, None, :] * (mist_layer * 0.25)
    else:
        rgb += mist_layer * c_accent[None, None, :] * 0.20

    # Organic Cinnabar Red accents (Day mode ONLY): small organic stamp/dot clusters
    if mode == "day":
        # Small organic seal stamp near left bank: center (width * 0.24, height * 0.68)
        dist_seal1 = np.sqrt(((x - width * 0.24) / 16.0) ** 2 + ((y - height * 0.68) / 20.0) ** 2)
        seal1 = np.exp(-(dist_seal1 ** 2)) * (0.85 + fine * 0.15)
        # Small organic dot mark near right bank: center (width * 0.76, height * 0.46)
        dist_seal2 = np.sqrt(((x - width * 0.76) / 14.0) ** 2 + ((y - height * 0.46) / 16.0) ** 2)
        seal2 = np.exp(-(dist_seal2 ** 2)) * (0.85 + stroke_noise * 0.15)

        cinnabar_mask = np.clip(seal1 * 0.90 + seal2 * 0.85, 0.0, 1.0)[..., None]
        rgb = rgb * (1.0 - cinnabar_mask * 0.92) + c_accent[None, None, :] * (cinnabar_mask * 0.92)

    # -------------------------------------------------------------------------
    # XUAN PAPER TEXTURE & MULTI-SCALE GRAIN
    # -------------------------------------------------------------------------
    # 1. Long diagonal primary fibers
    diag_fibers = np.sin(x * 0.032 + y * 0.36 + fine * 11.0)
    # 2. Fine cross fibers
    cross_fibers = np.sin(x * 0.078 - y * 0.24 + noise * 8.0)
    fibers = np.clip(diag_fibers - 0.82, 0.0, 0.18) + np.clip(cross_fibers - 0.88, 0.0, 0.12)

    # 3. Ink edge deposition (邊緣沉積)
    grad_x = np.abs(np.diff(ink_density[..., 0], axis=1, prepend=ink_density[:, :1, 0]))
    grad_y = np.abs(np.diff(ink_density[..., 0], axis=0, prepend=ink_density[:1, :, 0]))
    edge_depo = np.clip((grad_x + grad_y) * 4.5, 0.0, 1.0)[..., None]

    # Combine texture layers
    rgb += (noise[..., None] - 0.5) * 0.065
    rgb += (fine[..., None] - 0.5) * 0.032
    rgb += fibers[..., None] * 0.090
    rgb -= edge_depo * 0.080

    # Vignette subtle frame shading
    vignette = ((x - width * 0.5) / (width * 0.55)) ** 2 + ((y - height * 0.5) / (height * 0.55)) ** 2
    rgb -= vignette[..., None] * 0.030

    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def _fish_paper(
    palette: tuple[tuple[int, int, int], ...],
    noise: FloatArray,
    seed: int,
) -> FloatArray:
    """Build original sumi-e xuan paper and layered water wash background."""
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    fine = fbm(width, height, seed + 31, octaves=4, base=24)
    mid_noise = fbm(width, height, seed + 99, octaves=3, base=12)

    amount = np.clip(y / height + (noise - 0.5) * 0.08, 0.0, 1.0)[..., None]
    c0, c1, wash_c = _color(palette[0]), _color(palette[1]), _color(palette[2])
    rgb = c0[None, None, :] + (c1 - c0)[None, None, :] * amount

    wash_color = wash_c[None, None, :]
    for index, (center_rel_y, center_rel_x, radius_rel, strength) in enumerate(
        ((0.35, 0.25, 0.42, 0.075), (0.65, 0.75, 0.48, 0.085), (0.50, 0.50, 0.35, 0.060))
    ):
        dist = np.sqrt(
            ((x - width * center_rel_x) / (width * radius_rel)) ** 2
            + ((y - height * center_rel_y) / (height * radius_rel * 0.7)) ** 2
        )
        pool = np.exp(-(dist * (0.85 + mid_noise * 0.3)) ** 2)
        wave = np.sin(dist * 28.0 + seed * 0.1) * 0.5 + 0.5
        rgb += (pool * (0.6 + wave * 0.4))[..., None] * wash_color * strength

    for index, (center_y, breadth, strength) in enumerate(
        ((0.25, 0.12, 0.045), (0.52, 0.15, 0.055), (0.78, 0.14, 0.040))
    ):
        centerline = height * center_y + np.sin(x * (0.003 + index * 0.001) + seed) * height * 0.025
        centerline += (noise - 0.5) * height * 0.04
        band = np.exp(-((y - centerline) / (height * breadth)) ** 2)
        rgb += band[..., None] * wash_color * strength

    diagonal_fibers = np.sin(x * 0.026 + y * 0.38 + fine * 10.0)
    cross_fibers = np.sin(x * 0.068 - y * 0.22 + noise * 7.5)
    fibers = np.clip(diagonal_fibers - 0.85, 0.0, 0.15) + np.clip(cross_fibers - 0.90, 0.0, 0.10)

    rgb += (noise[..., None] - 0.5) * 0.070
    rgb += (fine[..., None] - 0.5) * 0.030
    rgb += fibers[..., None] * 0.090

    vignette = ((x - width * 0.5) / (width * 0.55)) ** 2 + ((y - height * 0.5) / (height * 0.55)) ** 2
    rgb -= vignette[..., None] * 0.035

    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def _render_koi_fish(
    x: FloatArray,
    y: FloatArray,
    noise: FloatArray,
    fine: FloatArray,
    center_x: float,
    center_y: float,
    angle: float,
    phase: float,
    fish_index: int,
) -> tuple[FloatArray, FloatArray]:
    """Render a sumi-e top-down koi fish frame with distinct body shape, fins, and markings."""
    width, height = WORK_SIZE
    length = 270.0
    body_width = 30.0

    delta_x = x - center_x
    delta_y = y - center_y
    cosine = np.cos(angle)
    sine = np.sin(angle)
    local_x = delta_x * cosine + delta_y * sine
    straight_y_raw = -delta_x * sine + delta_y * cosine

    u = local_x / length
    tail_weight = np.clip((-u + 0.35) / 1.35, 0.0, 1.0)
    centerline = np.sin((0.75 - u) * 2.1 + phase) * body_width * 0.45 * tail_weight
    straight_y = straight_y_raw - centerline

    # Body profile along vertical local_x
    u_body = np.clip((u - 0.02) / 0.76, -1.0, 1.0)
    core_profile = np.sqrt(np.clip(1.0 - u_body ** 2, 0.0, 1.0))
    width_profile = body_width * (0.15 + core_profile * 0.85)
    body_field = width_profile - np.abs(straight_y)
    body = _smoothstep(np.asarray((body_field + 2.5) / 8.0, dtype=np.float32))
    body *= _smoothstep(np.asarray((u + 0.65) / 0.10, dtype=np.float32))
    body *= _smoothstep(np.asarray((0.75 - u) / 0.10, dtype=np.float32))

    # Tail profile (Caudal fin) bounded within u = -0.95
    tail_progress = np.clip((-local_x - length * 0.50) / (length * 0.45), 0.0, 1.0)
    tail_center = np.sin(phase + tail_progress * 1.8) * body_width * (0.18 + tail_progress * 0.55)
    tail_domain = ((local_x < -length * 0.48) & (local_x > -length * 0.95)).astype(np.float32)
    tail_envelope = _smoothstep(np.asarray(tail_progress / 0.08, dtype=np.float32)) * _smoothstep(
        np.asarray((1.0 - tail_progress) / 0.15, dtype=np.float32)
    )
    spread = np.sin(tail_progress * np.pi)
    upper_wisp = tail_center - body_width * (0.10 + spread * 0.42)
    lower_wisp = tail_center + body_width * (0.10 + spread * 0.42)
    wisp_w = body_width * (0.10 + spread * 0.18)
    tail = np.exp(-((straight_y_raw - upper_wisp) / (wisp_w + 1.0)) ** 2) * 0.85
    tail += np.exp(-((straight_y_raw - lower_wisp) / (wisp_w + 1.0)) ** 2) * 0.78
    bridge = np.exp(-((straight_y_raw - tail_center) / (body_width * 0.18 + 1.0)) ** 4)
    bridge *= _smoothstep(np.asarray((0.35 - tail_progress) / 0.25, dtype=np.float32))
    tail += bridge * 0.82
    tail *= tail_domain * tail_envelope

    # Pectoral fins (compact X spread <= 80px total)
    fins = np.zeros((height, width), dtype=np.float32)
    for sign in (-1.0, 1.0):
        root_x = length * 0.32
        root_y = sign * body_width * 0.55
        tip_x = -length * (0.18 + 0.05 * np.sin(phase))
        tip_y = sign * body_width * (1.25 + 0.10 * np.cos(phase))
        vec_x = tip_x - root_x
        vec_y = tip_y - root_y
        fin_amount = np.clip(
            ((local_x - root_x) * vec_x + (straight_y_raw - root_y) * vec_y)
            / (vec_x * vec_x + vec_y * vec_y + 1e-5),
            0.0,
            1.0,
        )
        closest_x = root_x + fin_amount * vec_x
        closest_y = root_y + fin_amount * vec_y
        dist = np.sqrt((local_x - closest_x) ** 2 + (straight_y_raw - closest_y) ** 2)
        fin_w = body_width * (0.26 - fin_amount * 0.13)
        stroke = np.exp(-(dist / fin_w) ** 2) * np.clip(np.sin(fin_amount * np.pi), 0.0, 1.0) ** 0.40
        fins = np.maximum(fins, stroke)

    shape = np.maximum.reduce((body, np.clip(tail, 0.0, 1.0) * 0.85, fins * 0.78))
    bristles = np.sin(local_x * 0.085 + straight_y_raw * 0.030 + fine * 8.0) * 0.5 + 0.5
    granulation = np.clip(0.22 + noise * 0.72 + bristles * 0.18, 0.15, 1.0)
    alpha = shape * granulation

    head_x = length * 0.55
    eye_distance_left = np.sqrt((local_x - head_x) ** 2 + (straight_y - body_width * 0.38) ** 2)
    eye_distance_right = np.sqrt((local_x - head_x) ** 2 + (straight_y + body_width * 0.38) ** 2)
    eye_left = np.exp(-(eye_distance_left / 4.5) ** 4)
    eye_right = np.exp(-(eye_distance_right / 4.5) ** 4)
    eyes = np.maximum(eye_left, eye_right)
    alpha = np.maximum(alpha, eyes * 0.98)

    gill = np.exp(-((local_x - length * 0.36) / (length * 0.06)) ** 2) * np.exp(-(straight_y / (body_width * 0.65)) ** 4)

    if fish_index == 0:
        base_rgb = _color((242, 238, 226))[None, None, :]
        ink_spine = np.exp(-(straight_y / (body_width * 0.22 + 1.0)) ** 2) * np.clip(1.0 - np.abs(u), 0.0, 1.0)
        base_rgb = base_rgb * (0.75 + (noise[..., None] - 0.5) * 0.15 - ink_spine[..., None] * 0.12)

        red_head = np.exp(-(((local_x - length * 0.52) / 30.0) ** 2 + (straight_y / 18.0) ** 2))
        red_body = np.exp(-(((local_x + length * 0.05) / 55.0) ** 2 + ((straight_y - 4.0) / 22.0) ** 2))
        red_hi = np.clip(red_head * 1.1 + red_body * 1.0, 0.0, 1.0)

        red_color = _color((202, 45, 32))[None, None, :] * (0.80 + fine[..., None] * 0.35)
        rgb = base_rgb * (1.0 - red_hi[..., None]) + red_color * red_hi[..., None]
        rgb *= (1.0 - gill[..., None] * 0.15)
        rgb = rgb * (1.0 - eyes[..., None] * 0.90) + _color((20, 22, 28))[None, None, :] * eyes[..., None]

    elif fish_index == 1:
        base_rgb = _color((26, 28, 34))[None, None, :] * (0.65 + noise[..., None] * 0.45 + fine[..., None] * 0.15)

        patch_red = np.exp(-(((local_x - length * 0.45) / 34.0) ** 2 + ((straight_y - 5.0) / 18.0) ** 2))
        patch_gold = np.exp(-(((local_x + length * 0.12) / 48.0) ** 2 + ((straight_y + 6.0) / 20.0) ** 2))

        c_red = _color((215, 52, 35))[None, None, :] * (0.82 + fine[..., None] * 0.30)
        c_gold = _color((220, 155, 42))[None, None, :] * (0.82 + fine[..., None] * 0.30)

        rgb = base_rgb
        rgb = rgb * (1.0 - patch_red[..., None] * 0.88) + c_red * (patch_red[..., None] * 0.88)
        rgb = rgb * (1.0 - patch_gold[..., None] * 0.85) + c_gold * (patch_gold[..., None] * 0.85)
        gold_eye = eyes[..., None] * _color((225, 185, 55))[None, None, :]
        rgb = rgb * (1.0 - eyes[..., None] * 0.85) + gold_eye

    else:
        base_rgb = _color((212, 152, 54))[None, None, :] * (0.75 + noise[..., None] * 0.35 + fine[..., None] * 0.15)

        net_scale = np.sin(local_x * 0.18 + straight_y * 0.22) * np.sin(local_x * 0.18 - straight_y * 0.22)
        scale_mask = np.clip(net_scale * 0.5 + 0.5, 0.0, 1.0)
        spine_zone = np.exp(-(straight_y / (body_width * 0.55)) ** 2) * np.clip(1.0 - np.abs(u), 0.0, 1.0)
        indigo_scale = _color((48, 72, 98))[None, None, :] * (0.70 + fine[..., None] * 0.30)

        scale_influence = spine_zone * scale_mask * 0.75
        rgb = base_rgb * (1.0 - scale_influence[..., None]) + indigo_scale * scale_influence[..., None]
        rgb *= (1.0 - gill[..., None] * 0.18)
        rgb = rgb * (1.0 - eyes[..., None] * 0.90) + _color((24, 28, 36))[None, None, :] * eyes[..., None]

    alpha = feather_alpha(np.asarray(np.clip(alpha, 0.0, 0.96), dtype=np.float32), 4, 4)
    return alpha, np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def generate_fish_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    paper_noise = fbm(width, height, 4300, octaves=5, base=7)
    for index, (name, palette) in enumerate(PAPER_PALETTES.items()):
        paper = _fish_paper(palette, paper_noise, 4350 + index * 17)
        save_rgba(out / f"fish_base_{name}.png",
                  _rgba(paper, np.ones((height, width), np.float32)), False)

    # The PNG is baked at 2x. These centers map to the renderer's three
    # 220x330 output crops: 248/620/992 × 236.
    fish_specs = (
        (496, 472, -np.pi / 2.0, 4410, 0),
        (1240, 472, np.pi / 2.0, 4520, 1),
        (1984, 472, -np.pi / 2.0, 4630, 2),
    )
    for index, phase in enumerate((-0.86, 0.0, 0.86)):
        frame_rgb = np.zeros((height, width, 3), dtype=np.float32)
        frame_alpha = np.zeros((height, width), dtype=np.float32)
        for center_x, center_y, angle, seed, fish_idx in fish_specs:
            noise = fbm(width, height, seed, octaves=5, base=11)
            fine = fbm(width, height, seed + 31, octaves=3, base=29)
            alpha, rgb = _render_koi_fish(
                x, y, noise, fine, center_x, center_y, angle, phase, fish_idx,
            )
            take = alpha > frame_alpha
            frame_rgb[take] = rgb[take]
            frame_alpha = np.maximum(frame_alpha, alpha)
        # Ensure outer canvas edges are clean (alpha = 0)
        frame_alpha[0, :] = 0.0
        frame_alpha[-1, :] = 0.0
        frame_alpha[:, 0] = 0.0
        frame_alpha[:, -1] = 0.0
        save_rgba(out / f"fish_sprite_{index}.png",
                  _rgba(frame_rgb, frame_alpha), True)

    # Semi-transparent sumi-e water wake ripples for 2 wake overlay frames
    for index in range(2):
        wake_alpha = np.zeros((height, width), dtype=np.float32)
        wake_rgb = np.zeros((height, width, 3), dtype=np.float32)
        wake_noise = fbm(width, height, 4700 + index * 41, octaves=4, base=18)
        cyan_tint = np.asarray((0.72, 0.88, 0.94), dtype=np.float32)[None, None, :]

        for center_x, center_y, direction in (
            (496, 472, 1.0),
            (1240, 472, -1.0),
            (1984, 472, 1.0),
        ):
            local_x = x - center_x
            local_y = y - center_y
            forward = local_y * direction
            behind = np.clip(-forward / 160.0, 0.0, 1.0)

            # Concentric water ripples behind fish
            dist = np.sqrt(local_x ** 2 + local_y ** 2)
            ripple = np.sin((dist - index * 14.0) * 0.075) * 0.5 + 0.5
            ripple_env = np.exp(-((dist - 35.0 - index * 20.0) / 50.0) ** 2) * ripple

            # V-shaped trailing wake arcs
            v_wake = np.zeros((height, width), dtype=np.float32)
            for stroke, sign in enumerate((-1.0, 1.0)):
                curve = sign * (10.0 + behind * (32.0 + index * 6.0))
                curve += np.sin((-forward) * (0.028 + stroke * 0.005) + index) * (4.0 + behind * 5.0)
                width_scale = 3.5 + behind * 5.5
                v_wake += np.exp(-((local_x - curve) / width_scale) ** 2) * (0.60 - stroke * 0.08)

            length_fade = _smoothstep(np.asarray((forward + 180.0) / 45.0, dtype=np.float32))
            length_fade *= _smoothstep(np.asarray((30.0 - forward) / 30.0, dtype=np.float32))

            combined = np.maximum(v_wake * 0.75, ripple_env * 0.65) * length_fade
            wake_alpha = np.maximum(wake_alpha, combined)

        bristle = np.clip(0.45 + wake_noise * 0.70 + np.sin(y * 0.08 + wake_noise * 6.0) * 0.15, 0.20, 1.0)
        alpha = np.clip(wake_alpha * bristle * 0.85, 0.0, 0.95)
        alpha = feather_alpha(np.asarray(alpha, dtype=np.float32), 4, 4)

        # Force border edges to alpha = 0
        alpha[0, :] = 0.0
        alpha[-1, :] = 0.0
        alpha[:, 0] = 0.0
        alpha[:, -1] = 0.0

        luminance = np.clip(0.35 + wake_noise * 0.25, 0.25, 0.60)
        rgb = np.repeat(luminance[..., None], 3, axis=2) * cyan_tint
        save_rgba(out / f"fish_wake_{index}.png", _rgba(rgb, alpha), True)



def _pigment_bloom(
    x: FloatArray,
    y: FloatArray,
    index: int,
) -> tuple[FloatArray, FloatArray]:
    """Create wide-range asymmetric wet ink / mineral pigment flows composed of
    multiple irregular clusters, capillary bleeding, pigment accumulation edges,
    and ink fractures.
    """
    width, height = WORK_SIZE
    # `save_rgba` downsamples this 2x work canvas.  The renderer crops the
    # 320x320 output tile centered at (620, 236), so the pigment must be
    # centered at its corresponding 2x work coordinate.
    cx, cy = width / 2.0, height / 2.0

    local_x = x - cx
    local_y = y - cy

    low_noise = fbm(width, height, 5400 + index * 71, octaves=5, base=6)
    mid_noise = fbm(width, height, 5420 + index * 71, octaves=4, base=14)
    fine_noise = fbm(width, height, 5440 + index * 71, octaves=4, base=28)

    # Multi-cluster nodes per bloom index to guarantee asymmetric multi-lobed flows
    # Node tuple: (offset_x, offset_y, radius_x, radius_y, tilt_angle, weight)
    if index == 0:
        # Indigo / Lapis flow: Upper-left to lower-right diagonal flow with multiple nodes
        nodes = (
            (-65.0, -45.0, 65.0, 42.0, 0.4, 0.85),
            (55.0, 35.0, 58.0, 38.0, -0.3, 0.75),
            (-10.0, 45.0, 48.0, 35.0, 0.8, 0.65),
            (70.0, -50.0, 38.0, 26.0, 0.2, 0.55),
        )
    elif index == 1:
        # Cinnabar / Madder flow: Lower-left to upper-right flow with multiple nodes + tiny seal mark
        nodes = (
            (-60.0, 50.0, 60.0, 40.0, -0.5, 0.85),
            (48.0, -42.0, 52.0, 44.0, 0.3, 0.78),
            (12.0, -10.0, 42.0, 30.0, 0.6, 0.62),
            (-75.0, -35.0, 35.0, 25.0, -0.2, 0.50),
        )
    else:
        # Moss Green / Malachite flow: Horizontal river-like flow with multiple nodes
        nodes = (
            (-80.0, 10.0, 52.0, 44.0, 0.1, 0.82),
            (15.0, -48.0, 62.0, 36.0, -0.4, 0.80),
            (72.0, 35.0, 55.0, 38.0, 0.5, 0.72),
            (-15.0, 58.0, 40.0, 30.0, 0.2, 0.58),
        )

    # Domain warping for organic fluid dynamics
    work_scale = 2.0
    warp_x = local_x + (low_noise - 0.5) * 140.0 * work_scale + (mid_noise - 0.5) * 50.0 * work_scale
    warp_y = local_y + (mid_noise - 0.5) * 120.0 * work_scale + (fine_noise - 0.5) * 40.0 * work_scale

    raw_alpha = np.zeros((height, width), dtype=np.float32)
    accumulation = np.zeros((height, width), dtype=np.float32)

    # Evaluate each node with directional distortion and wet ink edge accumulation
    for off_x, off_y, rx, ry, tilt, weight in nodes:
        off_x *= work_scale
        off_y *= work_scale
        rx *= work_scale
        ry *= work_scale
        cos_t, sin_t = np.cos(tilt), np.sin(tilt)
        nx = (warp_x - off_x) * cos_t + (warp_y - off_y) * sin_t
        ny = -(warp_x - off_x) * sin_t + (warp_y - off_y) * cos_t

        dist_sq = (nx / rx) ** 2 + (ny / ry) ** 2
        # Node core wash
        node_wash = np.exp(-dist_sq * (0.85 + low_noise * 0.35)) * weight
        raw_alpha = np.maximum(raw_alpha, node_wash)

        # Edge accumulation (drying rim)
        rim = np.exp(-((dist_sq - 0.75) / 0.18) ** 2) * weight * 0.30
        accumulation = np.maximum(accumulation, rim)

    # Capillary bleed & paper fiber absorption along edges
    veins = np.abs(np.sin(warp_x * 0.030 + warp_y * 0.020 + low_noise * 10.0))
    capillary = np.clip(0.20 - veins, 0.0, 0.20) / 0.20
    capillary *= raw_alpha * np.clip((fine_noise - 0.35) * 2.8, 0.0, 1.0) * 0.25

    # Internal dry-brush fractures
    fractures = np.clip(1.0 - np.abs(mid_noise - 0.5) * 2.8, 0.20, 1.0)

    combined_alpha = (raw_alpha * 0.88 + accumulation * 0.65 + capillary) * fractures
    granulation = 0.68 + low_noise * 0.22 + fine_noise * 0.15
    combined_alpha *= granulation

    # The renderer crops a 320x320 output tile centered at (620, 236).  This
    # is a 640x640 window on the 2x work canvas; feather inside that window.
    crop_dist_x = np.abs(local_x)
    crop_dist_y = np.abs(local_y)
    crop_dist = np.maximum(crop_dist_x, crop_dist_y)
    crop_fade = _smoothstep(np.clip((308.0 - crop_dist) / 48.0, 0.0, 1.0))

    alpha = np.clip(combined_alpha * crop_fade * 1.40, 0.0, 0.95)
    alpha[alpha < 0.015] = 0.0
    alpha = feather_alpha(np.asarray(alpha, dtype=np.float32), 4, 4)

    # Force every pixel outside the renderer's source crop to strict zero.
    crop_x0, crop_x1 = round(cx - 320.0), round(cx + 320.0)
    crop_y0, crop_y1 = round(cy - 320.0), round(cy + 320.0)
    alpha[:crop_y0, :] = 0.0
    alpha[crop_y1:, :] = 0.0
    alpha[:, :crop_x0] = 0.0
    alpha[:, crop_x1:] = 0.0

    # Color tokens per bloom index
    if index == 0:
        base_color = _color((42, 95, 155))   # Lapis / Indigo
        core_color = _color((18, 38, 68))
        rim_color = _color((95, 155, 215))
    elif index == 1:
        base_color = _color((205, 65, 55))   # Cinnabar / Madder
        core_color = _color((115, 32, 42))
        rim_color = _color((240, 115, 95))
    else:
        base_color = _color((55, 135, 95))   # Malachite / Moss Green
        core_color = _color((26, 68, 48))
        rim_color = _color((115, 188, 145))

    density = np.clip(raw_alpha * (0.6 + accumulation * 0.8), 0.0, 1.0)[..., None]
    rgb = base_color[None, None, :] * (1.0 - density) + core_color[None, None, :] * density
    rgb += accumulation[..., None] * (rim_color - base_color)[None, None, :] * 0.60
    rgb += (fine_noise[..., None] - 0.5) * 0.05

    # Cinnabar organic seal mark in index == 1:
    if index == 1:
        # Small organic seal mark near one pigment cluster.
        seal_dx = np.abs(local_x - 35.0 * work_scale)
        seal_dy = np.abs(local_y - 20.0 * work_scale)
        seal_dist = np.maximum(seal_dx / (12.0 * work_scale), seal_dy / (14.0 * work_scale))
        seal_mask = _smoothstep(np.clip(1.0 - seal_dist, 0.0, 1.0)) * (0.75 + fine_noise * 0.25)
        seal_color = _color((195, 45, 35))[None, None, :]
        rgb = rgb * (1.0 - seal_mask[..., None] * 0.85) + seal_color * (seal_mask[..., None] * 0.85)
        alpha = np.maximum(alpha, seal_mask * 0.85 * crop_fade)

    return alpha, np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def generate_ink_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    paper_noise = fbm(width, height, 5300, octaves=5, base=8)
    for index, name in enumerate(("night", "dawn", "day")):
        paper = _ink_paper(name, paper_noise, 5350 + index * 19)
        save_rgba(out / f"ink_base_{name}.png",
                  _rgba(paper, np.ones((height, width), np.float32)), False)

    for index in range(3):
        alpha, rgb = _pigment_bloom(x, y, index)
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
