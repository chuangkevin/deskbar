"""Shared deterministic noise, feathering, and PNG production helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pygame
from numpy.typing import NDArray


OUTPUT_SIZE: Final = (1240, 472)
SUPERSAMPLE: Final = 2
WORK_SIZE: Final = (OUTPUT_SIZE[0] * SUPERSAMPLE, OUTPUT_SIZE[1] * SUPERSAMPLE)
FloatArray = NDArray[np.float32]


@dataclass(frozen=True)
class InvalidAssetArrayError(ValueError):
    __slots__ = ("actual_shape", "expected_shape")

    actual_shape: tuple[int, ...]
    expected_shape: tuple[int, ...]

    def __str__(self) -> str:
        return f"invalid RGBA work array: {self.actual_shape} != {self.expected_shape}"


@dataclass(frozen=True)
class AlphaBorderError(ValueError):
    __slots__ = ("path", "maximum_alpha")

    path: Path
    maximum_alpha: int

    def __str__(self) -> str:
        return f"alpha border leak in {self.path}: maximum alpha={self.maximum_alpha}"


def _smoothstep(values: FloatArray) -> FloatArray:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _value_noise(
    width: int,
    height: int,
    seed: int,
    grid_width: int,
    grid_height: int,
) -> FloatArray:
    generator = np.random.default_rng(seed)
    grid = generator.random((grid_height + 1, grid_width + 1), dtype=np.float32)
    xs = np.linspace(0.0, grid_width, width, endpoint=False, dtype=np.float32)
    ys = np.linspace(0.0, grid_height, height, endpoint=False, dtype=np.float32)
    x_index = np.minimum(xs.astype(np.int32), grid_width - 1)
    y_index = np.minimum(ys.astype(np.int32), grid_height - 1)
    x_amount = _smoothstep(xs - x_index)[None, :]
    y_amount = _smoothstep(ys - y_index)[:, None]
    top = (
        grid[y_index[:, None], x_index[None, :]] * (1.0 - x_amount)
        + grid[y_index[:, None], x_index[None, :] + 1] * x_amount
    )
    bottom = (
        grid[y_index[:, None] + 1, x_index[None, :]] * (1.0 - x_amount)
        + grid[y_index[:, None] + 1, x_index[None, :] + 1] * x_amount
    )
    return top * (1.0 - y_amount) + bottom * y_amount


def fbm(
    width: int,
    height: int,
    seed: int,
    octaves: int = 5,
    base: int = 4,
) -> FloatArray:
    """Return deterministic normalized fractal value noise."""
    result = np.zeros((height, width), dtype=np.float32)
    amplitude = 1.0
    total = 0.0
    for octave in range(octaves):
        grid_width = base * 2 ** octave
        grid_height = max(2, round(grid_width * height / width))
        result += _value_noise(
            width,
            height,
            seed + octave * 97,
            grid_width,
            grid_height,
        ) * amplitude
        total += amplitude
        amplitude *= 0.5
    return result / total


def feather_alpha(alpha: FloatArray, border_x: int, border_y: int) -> FloatArray:
    """Fade an alpha plane to exact zero on all four source borders."""
    height, width = alpha.shape
    y, x = np.mgrid[0:height, 0:width]
    fade_x = np.minimum(
        np.clip(x / border_x, 0.0, 1.0),
        np.clip((width - 1 - x) / border_x, 0.0, 1.0),
    )
    fade_y = np.minimum(
        np.clip(y / border_y, 0.0, 1.0),
        np.clip((height - 1 - y) / border_y, 0.0, 1.0),
    )
    return np.asarray(alpha * _smoothstep(fade_x.astype(np.float32))
                      * _smoothstep(fade_y.astype(np.float32)), dtype=np.float32)


def save_rgba(path: Path, rgba: FloatArray, transparent: bool) -> None:
    """Downsample one supersampled float RGBA work canvas deterministically."""
    expected = (WORK_SIZE[1], WORK_SIZE[0], 4)
    if rgba.shape != expected:
        raise InvalidAssetArrayError(tuple(rgba.shape), expected)
    pixels = np.clip(rgba * 255.0, 0.0, 255.0).astype(np.uint8)
    source = pygame.image.frombuffer(pixels.tobytes(), WORK_SIZE, "RGBA").copy()
    output = pygame.transform.smoothscale(source, OUTPUT_SIZE)
    alpha = pygame.surfarray.pixels_alpha(output)
    if transparent:
        alpha[0, :] = alpha[-1, :] = 0
        alpha[:, 0] = alpha[:, -1] = 0
    else:
        alpha[:, :] = 255
    del alpha
    pygame.image.save(output, str(path))


def validate_alpha_edges(path: Path) -> None:
    """Reject a movable overlay whose decoded border is not fully transparent."""
    alpha = pygame.surfarray.array_alpha(pygame.image.load(str(path)))
    edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
    maximum = int(edges.max())
    if maximum != 0:
        raise AlphaBorderError(path, maximum)
