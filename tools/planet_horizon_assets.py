"""Supersampled matte-painting baker for the planetary-horizon scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pygame


OUTPUT_SIZE: Final = (1180, 472)
SUPERSAMPLE: Final = 2


@dataclass(frozen=True)
class PlanetPalette:
    """Authored color anchors for one real-world lighting state."""

    __slots__ = ("name", "zenith", "horizon", "shadow", "bands", "rim",
                 "clouds", "stars")

    name: str
    zenith: tuple[int, int, int]
    horizon: tuple[int, int, int]
    shadow: tuple[int, int, int]
    bands: tuple[int, int, int]
    rim: tuple[int, int, int]
    clouds: tuple[int, int, int]
    stars: float


PALETTES: Final = (
    PlanetPalette("night", (2, 7, 18), (8, 23, 46), (5, 9, 18),
                  (54, 79, 103), (116, 192, 255), (88, 126, 159), 1.0),
    PlanetPalette("dawn", (18, 25, 48), (86, 104, 132), (20, 27, 41),
                  (112, 126, 142), (178, 221, 255), (179, 191, 203), 0.32),
    PlanetPalette("day", (32, 67, 105), (111, 157, 190), (38, 54, 67),
                  (150, 169, 178), (208, 239, 255), (222, 231, 234), 0.0),
)


def _smoothstep(values: "np.ndarray") -> "np.ndarray":
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _value_noise(width: int, height: int, seed: int,
                 grid_width: int, grid_height: int) -> "np.ndarray":
    rng = np.random.default_rng(seed)
    grid = rng.random((grid_height + 1, grid_width + 1), dtype=np.float32)
    xs = np.linspace(0.0, grid_width, width, endpoint=False, dtype=np.float32)
    ys = np.linspace(0.0, grid_height, height, endpoint=False, dtype=np.float32)
    xi = np.minimum(xs.astype(np.int32), grid_width - 1)
    yi = np.minimum(ys.astype(np.int32), grid_height - 1)
    xf = _smoothstep(xs - xi)[None, :]
    yf = _smoothstep(ys - yi)[:, None]
    top = grid[yi[:, None], xi[None, :]] * (1.0 - xf) \
        + grid[yi[:, None], xi[None, :] + 1] * xf
    bottom = grid[yi[:, None] + 1, xi[None, :]] * (1.0 - xf) \
        + grid[yi[:, None] + 1, xi[None, :] + 1] * xf
    return top * (1.0 - yf) + bottom * yf


def _fbm(width: int, height: int, seed: int, base: int,
         octaves: int = 5) -> "np.ndarray":
    acc = np.zeros((height, width), dtype=np.float32)
    amplitude = 1.0
    total = 0.0
    for octave in range(octaves):
        grid_width = base * 2 ** octave
        grid_height = max(2, round(grid_width * height / width))
        acc += _value_noise(width, height, seed + octave * 97,
                            grid_width, grid_height) * amplitude
        total += amplitude
        amplitude *= 0.5
    return acc / total


def _color(rgb: tuple[int, int, int]) -> "np.ndarray":
    return np.asarray(rgb, dtype=np.float32) / 255.0


def _mix(a: "np.ndarray", b: "np.ndarray", amount: "np.ndarray") -> "np.ndarray":
    return a + (b - a) * amount[..., None]


def _add_stars(rgb: "np.ndarray", strength: float, seed: int) -> None:
    if strength <= 0.0:
        return
    height, width = rgb.shape[:2]
    rng = np.random.default_rng(seed)
    for _ in range(150):
        x = int(rng.integers(12, width - 12))
        y = int(rng.integers(8, round(height * 0.62)))
        radius = int(rng.choice((1, 1, 1, 2, 2, 3)))
        intensity = float(rng.uniform(0.22, 0.78) * strength)
        yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
        glow = np.exp(-(xx * xx + yy * yy) / max(1.0, radius * radius))
        patch = rgb[y - radius:y + radius + 1, x - radius:x + radius + 1]
        patch += glow[..., None] * intensity


def _planet_master(palette: PlanetPalette, seed: int) -> "np.ndarray":
    width, height = (value * SUPERSAMPLE for value in OUTPUT_SIZE)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    y_norm = yy / (height - 1)
    sky_amount = _smoothstep(y_norm / 0.78)
    rgb = _mix(np.broadcast_to(_color(palette.zenith), (height, width, 3)),
               np.broadcast_to(_color(palette.horizon), (height, width, 3)),
               sky_amount)

    _add_stars(rgb, palette.stars, seed + 900)
    backlight = np.exp(-(((xx - width * 0.88) / (width * 0.30)) ** 2
                         + ((yy - height * 0.60) / (height * 0.24)) ** 2)) * 0.32
    rgb = _mix(rgb, np.broadcast_to(_color(palette.rim), rgb.shape), backlight)

    cx, cy, radius = width * 0.58, -height * 0.32, height * 0.95
    px = (xx - cx) / radius
    py = (yy - cy) / radius
    radial = np.sqrt(px * px + py * py)
    inside = radial <= 1.0
    nz = np.sqrt(np.clip(1.0 - radial * radial, 0.0, 1.0))
    light = np.clip(px * 0.26 + py * 0.77 + nz * 0.42, -1.0, 1.0)
    illumination = _smoothstep((light + 0.18) / 0.78) ** 1.45

    broad = _fbm(width, height, seed, 4, 4)
    detail = _fbm(width, height, seed + 200, 15, 5)
    fine = _fbm(width, height, seed + 350, 38, 3)
    shear = np.sin(px * 8.0 + broad * 3.0) * 0.022
    warped_latitude = py + (broad - 0.5) * 0.15 + shear
    gas_bands = 0.48 + 0.20 * np.sin(warped_latitude * 39.0) \
        + 0.11 * np.sin(warped_latitude * 91.0 + detail * 7.0)
    material = np.clip(gas_bands + (detail - 0.5) * 0.30
                       + (fine - 0.5) * 0.14, 0.04, 0.98)
    storm = np.exp(-(((px + 0.12) / 0.17) ** 2
                     + ((py - 0.28) / 0.075) ** 2))
    material = np.clip(material + storm * np.sin(px * 64.0 + detail * 9.0) * 0.12,
                       0.02, 1.0)
    limb = np.clip(nz ** 0.34, 0.0, 1.0)
    authored_light = np.clip(0.035 + illumination * (0.38 + material * 0.46),
                             0.0, 1.0)
    planet = _mix(np.broadcast_to(_color(palette.shadow), (height, width, 3)),
                  np.broadcast_to(_color(palette.bands), (height, width, 3)),
                  authored_light * (0.52 + limb * 0.48))
    planet *= (0.80 + material[..., None] * 0.28)
    rgb[inside] = planet[inside]

    edge_light = np.clip(px * 0.78 + py * 0.52, 0.0, 1.0) ** 2.2
    edge_distance = np.abs(radial - 1.0) * radius
    rim_core = np.exp(-(edge_distance / (1.5 * SUPERSAMPLE)) ** 2) * edge_light
    rim_glow = np.exp(-(edge_distance / (12.0 * SUPERSAMPLE)) ** 2) * edge_light * 0.28
    rim_amount = np.clip(rim_core * 0.90 + rim_glow, 0.0, 1.0)
    rgb = _mix(rgb, np.broadcast_to(_color(palette.rim), rgb.shape), rim_amount)

    horizon_y = height * (0.62 + 0.028 * ((xx - width * 0.5) / (width * 0.5)) ** 2)
    depth = np.clip((yy - horizon_y) / (height * 0.39), 0.0, 1.0)
    cloud_mass = _fbm(width, height, seed + 500, 8, 5)
    cloud_detail = _fbm(width, height, seed + 700, 26, 4)
    cloud_fine = _fbm(width, height, seed + 820, 54, 3)
    cloud_field = cloud_mass * 0.58 + cloud_detail * 0.30 + cloud_fine * 0.12
    cloud_density = _smoothstep((cloud_field + depth * 0.56 - 0.54) * 4.0)
    cloud_gate = _smoothstep((yy - horizon_y + 42 * SUPERSAMPLE)
                             / (86 * SUPERSAMPLE))
    cloud_density *= cloud_gate
    cloud_density = np.maximum(cloud_density, depth ** 1.50 * 0.82)
    cloud_shadow = _color(tuple(round(value * 0.45) for value in palette.clouds))
    cloud_light = _color(palette.clouds)
    relief = cloud_field - np.roll(cloud_field, shift=(7 * SUPERSAMPLE,
                                                       -9 * SUPERSAMPLE), axis=(0, 1))
    cloud_luminance = np.clip(0.20 + cloud_mass * 0.40 + cloud_detail * 0.22
                              + cloud_fine * 0.12 + relief * 2.8
                              + (1.0 - depth) * 0.14, 0.0, 1.0)
    clouds = _mix(np.broadcast_to(cloud_shadow, rgb.shape),
                  np.broadcast_to(cloud_light, rgb.shape), cloud_luminance)
    rgb = _mix(rgb, clouds, cloud_density)

    haze = np.exp(-((yy - horizon_y) / (18.0 * SUPERSAMPLE)) ** 2) * 0.45
    rgb = _mix(rgb, np.broadcast_to(_color(palette.rim), rgb.shape), haze)
    grain = np.random.default_rng(seed + 1000).normal(0.0, 0.0045, rgb.shape[:2])
    rgb += grain[..., None]
    alpha = np.ones((height, width, 1), dtype=np.float32)
    return np.concatenate((np.clip(rgb, 0.0, 1.0), alpha), axis=2)


def _cloud_layer(seed: int, center_y: float, spread: float,
                 detail_base: int) -> "np.ndarray":
    width, height = (value * SUPERSAMPLE for value in OUTPUT_SIZE)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    mass = _fbm(width, height, seed, 5, 5)
    detail = _fbm(width, height, seed + 110, detail_base, 4)
    band = np.exp(-((yy / height - center_y) / spread) ** 2)
    density = _smoothstep((mass * 0.72 + detail * 0.28 - 0.49) * 4.0) * band
    fade_x = np.minimum(np.clip(xx / (32 * SUPERSAMPLE), 0.0, 1.0),
                        np.clip((width - 1 - xx) / (32 * SUPERSAMPLE), 0.0, 1.0))
    fade_y = np.minimum(np.clip(yy / (12 * SUPERSAMPLE), 0.0, 1.0),
                        np.clip((height - 1 - yy) / (12 * SUPERSAMPLE), 0.0, 1.0))
    alpha = density * _smoothstep(fade_x) * _smoothstep(fade_y) * 0.72
    luminance = np.clip(0.58 + mass * 0.30 + detail * 0.16
                        - yy / height * 0.12, 0.0, 1.0)
    rgb = np.repeat(luminance[..., None], 3, axis=2)
    return np.concatenate((rgb, alpha[..., None]), axis=2)


def _save_supersampled(path: Path, rgba: "np.ndarray", transparent: bool) -> None:
    height, width = rgba.shape[:2]
    pixels = np.clip(rgba * 255.0, 0.0, 255.0).astype(np.uint8)
    source = pygame.image.frombuffer(pixels.tobytes(), (width, height), "RGBA").copy()
    surface = pygame.transform.smoothscale(source, OUTPUT_SIZE)
    if transparent:
        alpha = pygame.surfarray.pixels_alpha(surface)
        alpha[0, :] = alpha[-1, :] = 0
        alpha[:, 0] = alpha[:, -1] = 0
        del alpha
    pygame.image.save(surface, str(path))
    print(f"  {path.name}  {OUTPUT_SIZE[0]}x{OUTPUT_SIZE[1]}")


def generate_planet_horizon_assets(out: Path) -> None:
    """Bake all time-state masters and movable cloud overlays."""
    for index, palette in enumerate(PALETTES):
        _save_supersampled(out / f"planet_horizon_{palette.name}.png",
                           _planet_master(palette, 7400 + index * 100), False)
    _save_supersampled(out / "planet_cloud_far.png",
                       _cloud_layer(8110, 0.66, 0.13, 14), True)
    _save_supersampled(out / "planet_cloud_near.png",
                       _cloud_layer(8220, 0.84, 0.18, 10), True)
