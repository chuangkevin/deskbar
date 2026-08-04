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
    "night": ((14, 23, 36), (44, 58, 70), (93, 123, 137)),
    "dawn": ((62, 50, 62), (145, 118, 108), (188, 145, 117)),
    "day": ((198, 197, 181), (235, 226, 199), (112, 148, 153)),
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
    """Build irregular paper/water wash without directional stripe artifacts."""
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


def _fish_mask(
    x: FloatArray,
    y: FloatArray,
    noise: FloatArray,
    fine: FloatArray,
    center_x: float,
    center_y: float,
    angle: float,
    phase: float,
) -> tuple[FloatArray, FloatArray]:
    """Return one top-down koi animation frame with an articulated ink tail."""
    width, height = WORK_SIZE
    length = 132.0
    body_height = 45.0
    delta_x = x - center_x
    delta_y = y - center_y
    cosine = np.cos(angle)
    sine = np.sin(angle)
    local_x = delta_x * cosine + delta_y * sine
    straight_y = -delta_x * sine + delta_y * cosine
    u = local_x / length
    tail_weight = np.clip((-u + 0.38) / 1.35, 0.10, 1.0)
    centerline = np.sin((1.0 - u) * 1.95 + phase) * body_height * 0.54 * tail_weight
    centerline += np.sin(phase) * body_height * 0.08
    local_y = straight_y - centerline

    profile_core = np.sqrt(np.clip(1.0 - ((u + 0.01) / 1.04) ** 2, 0.0, 1.0))
    profile = body_height * (0.06 + profile_core * 0.94)
    body_field = profile - np.abs(local_y) * (1.02 + np.clip(-u, 0.0, 1.0) * 0.18)
    body = _smoothstep(np.asarray((body_field + 2.0) / 8.0, dtype=np.float32))
    body *= _smoothstep(np.asarray((u + 1.08) / 0.11, dtype=np.float32))
    body *= _smoothstep(np.asarray((1.07 - u) / 0.11, dtype=np.float32))

    tail_progress = np.clip((-local_x - length * 0.78) / (length * 0.92), 0.0, 1.0)
    tail_center = np.sin(phase + tail_progress * 1.82) * body_height \
        * (0.12 + tail_progress * 0.58)
    tail_domain = ((local_x < -length * 0.76)
                   & (local_x > -length * 1.72)).astype(np.float32)
    tail_envelope = _smoothstep(np.asarray(tail_progress / 0.10, dtype=np.float32)) \
        * _smoothstep(np.asarray((1.0 - tail_progress) / 0.16, dtype=np.float32))
    spread = np.sin(tail_progress * np.pi)
    upper_wisp = tail_center - body_height * spread * 0.62
    lower_wisp = tail_center + body_height * spread * 0.52
    wisp_width = body_height * (0.10 + spread * 0.20)
    tail = np.exp(-((straight_y - upper_wisp) / (wisp_width + 1.0)) ** 2) * 0.78
    tail += np.exp(-((straight_y - lower_wisp) / (wisp_width + 1.0)) ** 2) * 0.68
    bridge = np.exp(-((straight_y - tail_center) / (body_height * 0.16 + 1.0)) ** 4)
    bridge *= _smoothstep(np.asarray((0.34 - tail_progress) / 0.24,
                                     dtype=np.float32))
    tail += bridge * 0.76
    tail *= tail_domain * tail_envelope

    fins = np.zeros((height, width), dtype=np.float32)
    for sign in (-1.0, 1.0):
        root_x = length * 0.38
        root_y = sign * body_height * 0.58
        tip_x = -length * (0.34 + 0.06 * np.sin(phase))
        tip_y = sign * body_height * (1.72 + 0.14 * np.cos(phase))
        vector_x = tip_x - root_x
        vector_y = tip_y - root_y
        fin_amount = np.clip(
            ((local_x - root_x) * vector_x + (local_y - root_y) * vector_y)
            / (vector_x * vector_x + vector_y * vector_y),
            0.0,
            1.0,
        )
        closest_x = root_x + fin_amount * vector_x
        closest_y = root_y + fin_amount * vector_y
        distance = np.sqrt((local_x - closest_x) ** 2 + (local_y - closest_y) ** 2)
        width_profile = body_height * (0.31 - fin_amount * 0.15)
        stroke = np.exp(-(distance / width_profile) ** 2) \
            * np.clip(np.sin(fin_amount * np.pi), 0.0, 1.0) ** 0.42
        fins = np.maximum(fins, stroke)

    shape = np.maximum.reduce((body, np.clip(tail, 0.0, 1.0) * 0.76, fins * 0.76))
    bristles = np.sin(local_x * 0.087 + straight_y * 0.031 + fine * 8.0) * 0.5 + 0.5
    granulation = np.clip(0.18 + noise * 0.76 + bristles * 0.17, 0.12, 1.0)
    dry_gaps = np.where((fine < 0.38) & (bristles < 0.41), 0.20, 1.0)
    alpha = shape * granulation * dry_gaps
    alpha += np.clip(shape - 0.78, 0.0, 0.22) * 0.24

    head_ink = np.exp(-(((local_x - length * 0.62) / (length * 0.34)) ** 2
                        + (local_y / (body_height * 0.78)) ** 2))
    spine = np.exp(-(local_y / (body_height * 0.16 + 1.0)) ** 2) \
        * np.clip(1.0 - np.abs(u), 0.0, 1.0)
    luminance = np.clip(0.62 + noise * 0.27 + fine * 0.09
                        - head_ink * 0.14 - spine * 0.13, 0.36, 0.98)

    eye_x = length * 0.67
    for eye_y in (-body_height * 0.28, body_height * 0.28):
        eye_distance = np.sqrt((local_x - eye_x) ** 2 + (local_y - eye_y) ** 2)
        eye = np.exp(-(eye_distance / 4.5) ** 4)
        alpha = np.maximum(alpha, eye * 0.98)
        luminance = luminance * (1.0 - eye * 0.82) + eye * 0.08

    gill = np.exp(-((local_x - length * 0.43) / (length * 0.055)) ** 2) \
        * np.exp(-(local_y / (body_height * 0.68)) ** 4)
    luminance *= 1.0 - gill * 0.18
    alpha = feather_alpha(np.asarray(np.clip(alpha, 0.0, 0.96), dtype=np.float32), 4, 4)
    return alpha, np.asarray(luminance, dtype=np.float32)


def generate_fish_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width, height = WORK_SIZE
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    paper_noise = fbm(width, height, 4300, octaves=5, base=7)
    for index, (name, palette) in enumerate(PAPER_PALETTES.items()):
        paper = _paper(palette, paper_noise, 4350 + index * 17)
        save_rgba(out / f"fish_base_{name}.png",
                  _rgba(paper, np.ones((height, width), np.float32)), False)

    fish_specs = (
        (width * 0.28, height * 0.5, -np.pi / 2.0, (30, 32, 34), 4410),
        (width * 0.72, height * 0.5, np.pi / 2.0, (193, 54, 43), 4520),
    )
    for index, phase in enumerate((-0.86, 0.0, 0.86)):
        frame_rgb = np.zeros((height, width, 3), dtype=np.float32)
        frame_alpha = np.zeros((height, width), dtype=np.float32)
        for center_x, center_y, angle, color, seed in fish_specs:
            noise = fbm(width, height, seed, octaves=5, base=11)
            fine = fbm(width, height, seed + 31, octaves=3, base=29)
            alpha, luminance = _fish_mask(
                x, y, noise, fine, center_x, center_y, angle, phase,
            )
            if color[0] < 50:
                ink = 0.025 + luminance * 0.15
                pigment = np.repeat(ink[..., None], 3, axis=2)
            else:
                pigment = _color(color)[None, None, :] * (0.34 + luminance[..., None] * 0.66)
            pigment += (fine[..., None] - 0.5) * 0.018
            take = alpha > frame_alpha
            frame_rgb[take] = pigment[take]
            frame_alpha = np.maximum(frame_alpha, alpha)
        save_rgba(out / f"fish_sprite_{index}.png",
                  _rgba(frame_rgb, frame_alpha), True)

    local_x = x - width * 0.5
    local_y = y - height * 0.5
    for index, direction in enumerate((-1.0, 1.0)):
        forward = local_y * direction
        behind = np.clip(-forward / 270.0, 0.0, 1.0)
        wake = np.zeros((height, width), dtype=np.float32)
        wake_noise = fbm(width, height, 4700 + index * 41, octaves=4, base=18)
        for stroke, sign in enumerate((-1.0, 1.0)):
            curve = sign * (8.0 + behind * (31.0 + index * 8.0))
            curve += np.sin((-forward) * (0.030 + stroke * 0.004) + index) \
                * (4.0 + behind * 5.0)
            width_scale = 3.2 + behind * 5.0
            wake += np.exp(-((local_x - curve) / width_scale) ** 2) * (0.58 - stroke * 0.06)
        center_curve = np.sin((-forward) * 0.052 + index * 1.7) * 4.5
        wake += np.exp(-((local_x - center_curve) / (2.7 + behind * 3.0)) ** 2) * 0.42
        length_fade = _smoothstep(np.asarray((forward + 278.0) / 52.0, dtype=np.float32))
        length_fade *= _smoothstep(np.asarray((28.0 - forward) / 42.0, dtype=np.float32))
        bristle = np.clip(0.42 + wake_noise * 0.74
                          + np.sin(forward * 0.12 + wake_noise * 7.0) * 0.16, 0.18, 1.0)
        alpha = np.clip(wake * length_fade * bristle * (0.94 - behind * 0.18), 0.0, 0.96)
        alpha = feather_alpha(np.asarray(alpha, dtype=np.float32), 4, 4)
        wake_luminance = np.clip(0.25 + wake_noise * 0.19, 0.20, 0.48)
        rgb = np.repeat(wake_luminance[..., None], 3, axis=2)
        rgb *= np.asarray((0.78, 0.91, 0.96), dtype=np.float32)[None, None, :]
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
