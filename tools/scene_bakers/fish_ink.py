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


def _paper(
    palette: tuple[tuple[int, int, int], ...],
    noise: FloatArray,
    seed: int,
) -> FloatArray:
    """Build the established paper wash used by the already-approved ink scene."""
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    fine = fbm(width, height, seed + 31, octaves=4, base=24)
    amount = np.clip(y / height + (noise - 0.5) * 0.075, 0.0, 1.0)[..., None]
    rgb = _color(palette[0])[None, None, :] + (
        _color(palette[1]) - _color(palette[0])
    )[None, None, :] * amount

    wash_color = _color(palette[2])[None, None, :]
    for index, (center, breadth, strength) in enumerate(
        ((0.22, 0.10, 0.050), (0.51, 0.16, 0.065), (0.78, 0.13, 0.045))
    ):
        centerline = height * center + np.sin(x * (0.0024 + index * 0.0007) + seed) \
            * height * (0.018 + index * 0.006)
        centerline += (noise - 0.5) * height * 0.055
        band = np.exp(-((y - centerline) / (height * breadth)) ** 2)
        rgb += band[..., None] * wash_color * strength

    diagonal_fibers = np.sin(x * 0.028 + y * 0.39 + fine * 11.0)
    cross_fibers = np.sin(x * 0.071 - y * 0.23 + noise * 8.0)
    fibers = np.clip(diagonal_fibers - 0.86, 0.0, 0.14) \
        + np.clip(cross_fibers - 0.92, 0.0, 0.08)
    rgb += (noise[..., None] - 0.5) * 0.095
    rgb += (fine[..., None] - 0.5) * 0.035
    rgb += fibers[..., None] * 0.12
    vignette = ((x - width * 0.5) / width) ** 2 + ((y - height * 0.5) / height) ** 2
    rgb -= vignette[..., None] * 0.025
    return np.asarray(rgb, dtype=np.float32)


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
    """Create a soft watercolor deposit with granulation and capillary edges."""
    width, height = WORK_SIZE
    local_x = x - width * 0.5
    local_y = y - height * 0.5
    low = fbm(width, height, 5400 + index * 71, octaves=5, base=7)
    fine = fbm(width, height, 5440 + index * 71, octaves=4, base=23)

    angle = (-0.18, 0.26, -0.32)[index]
    cosine, sine = np.cos(angle), np.sin(angle)
    rotated_x = local_x * cosine - local_y * sine
    rotated_y = local_x * sine + local_y * cosine
    radius = np.sqrt((rotated_x / (1.12 + index * 0.04)) ** 2
                     + (rotated_y / (0.84 + index * 0.04)) ** 2)
    warped_radius = radius * (0.64 + low * 0.64) + (fine - 0.5) * 11.0

    bloom_radius = 220.0 + index * 12.0
    interior = _smoothstep(np.asarray((bloom_radius - warped_radius) / 42.0 + 0.54,
                                      dtype=np.float32))
    halo = np.exp(-(warped_radius / (bloom_radius * 1.19)) ** 4) * 0.20
    broken_edge = np.clip(
        0.16 + fine * 0.92
        + np.sin(local_x * 0.031 - local_y * 0.026 + low * 7.0) * 0.18,
        0.0,
        1.0,
    )
    accumulation = np.exp(-((warped_radius - bloom_radius * 0.91) / 14.0) ** 2) \
        * broken_edge * 0.28

    deposits = np.zeros((height, width), dtype=np.float32)
    deposit_specs = (
        (-64.0, -31.0, 92.0),
        (47.0, -39.0, 105.0),
        (-8.0, 62.0, 116.0),
        (78.0, 56.0, 76.0),
    )
    for lobe, (offset_x, offset_y, breadth) in enumerate(deposit_specs):
        offset_x += index * (7 - lobe * 3)
        offset_y += index * (lobe * 4 - 6)
        deposits += np.exp(-(((local_x - offset_x) / breadth) ** 2
                             + ((local_y - offset_y) / (breadth * 0.83)) ** 2)) \
            * (0.10 + lobe * 0.018)

    veins = np.abs(np.sin(
        local_x * (0.023 + index * 0.002)
        + local_y * (0.017 - index * 0.001)
        + low * 10.0,
    ))
    capillary = np.clip(0.17 - veins, 0.0, 0.17) / 0.17
    capillary *= interior * np.clip((fine - 0.42) * 2.8, 0.0, 1.0) * 0.13
    granulation = 0.48 + low * 0.31 + fine * 0.16
    alpha = np.clip(interior * granulation * 0.62 + halo + accumulation + deposits + capillary,
                    0.0, 0.88)
    alpha *= np.clip(0.68 + fine * 0.50, 0.0, 1.0)
    support_distance = np.sqrt(local_x * local_x + local_y * local_y)
    support = _smoothstep(np.asarray((286.0 - support_distance) / 56.0,
                                     dtype=np.float32))
    alpha *= support
    alpha[alpha < 0.018] = 0.0
    # Runtime extracts a centered 320x320 source tile. Fade inside that tile so
    # its bounds cannot appear as rectangular seams when the bloom is scaled.
    crop_distance = np.maximum(np.abs(local_x), np.abs(local_y))
    crop_fade = _smoothstep(np.asarray((310.0 - crop_distance) / 64.0,
                                       dtype=np.float32))
    alpha *= crop_fade
    alpha = feather_alpha(np.asarray(alpha, dtype=np.float32), 4, 4)

    pigment_light = np.clip(0.62 + low * 0.28 - accumulation * 0.42
                            + (fine - 0.5) * 0.12, 0.34, 0.92)
    return alpha, np.asarray(pigment_light, dtype=np.float32)


def generate_ink_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    paper_noise = fbm(width, height, 5300, octaves=5, base=8)
    for index, (name, palette) in enumerate(INK_PAPER_PALETTES.items()):
        paper = _paper(palette, paper_noise, 5350 + index * 19)
        stain_noise = fbm(width, height, 5370 + index * 19, octaves=4, base=5)
        for center_x, center_y, radius, strength in (
            (0.18, 0.68, 0.24, 0.025),
            (0.54, 0.28, 0.31, 0.018),
            (0.86, 0.73, 0.27, 0.022),
        ):
            distance = np.sqrt(((x / width - center_x) / radius) ** 2
                               + ((y / height - center_y) / (radius * 0.62)) ** 2)
            stain = np.exp(-(distance * (0.88 + stain_noise * 0.24)) ** 4)
            paper -= stain[..., None] * _color(palette[2])[None, None, :] * strength
        save_rgba(out / f"ink_base_{name}.png",
                  _rgba(paper, np.ones((height, width), np.float32)), False)

    colors = ((35, 74, 101), (120, 53, 72), (43, 91, 70))
    for index, color in enumerate(colors):
        alpha, pigment_light = _pigment_bloom(x, y, index)
        rgb = _color(color)[None, None, :] * pigment_light[..., None]
        rgb += (1.0 - pigment_light[..., None]) * _color((20, 24, 29))[None, None, :] * 0.10
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
