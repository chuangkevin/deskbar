from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import scene_runner, scenes


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET_DIR = Path("deskbar/assets/scenes")
NOW = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
BASES = tuple(
    f"{scene}_base_{light}"
    for scene in ("train", "runner")
    for light in ("night", "dawn", "day")
)
OVERLAYS = (
    "train_far",
    "train_mid",
    "train_near",
    "train_window_reflection",
    "runner_far",
    "runner_mid",
    "runner_near",
    "runner_sprite_sheet",
    "runner_obstacles",
)


def _render(kind: str, t: float) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    scenes.render(surface, state, NOW, t, enabled=(kind,), weather_code=1)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _motion_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def test_pixel_assets_use_authored_canvas_clean_edges_and_nearest_scaling() -> None:
    for name in (*BASES, *OVERLAYS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        rgb = pygame.surfarray.array3d(surface)
        assert np.array_equal(rgb[0::2, 0::2], rgb[1::2, 0::2]), name
        assert np.array_equal(rgb[0::2, 0::2], rgb[0::2, 1::2]), name
        alpha = pygame.surfarray.array_alpha(surface)
        if "_base_" in name:
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name


def test_train_and_runner_palette_motion_determinism_and_memory() -> None:
    for kind in ("train", "runner"):
        first, decoded = _render(kind, 0.0)
        repeated, repeated_decoded = _render(kind, 0.0)
        later, _ = _render(kind, 15.0)
        array = np.frombuffer(first, np.uint8).reshape(472, 1118, 3)
        sampled = array[::8, ::8].reshape(-1, 3)
        assert first == repeated
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        assert len(np.unique(sampled, axis=0)) >= 48
        ratio = _motion_ratio(first, later)
        assert 0.05 <= ratio <= 0.45, (kind, ratio)


def test_runner_obstacle_schedule_is_deterministic() -> None:
    first = [scene_runner.obstacle_phase(float(second), 810616) for second in range(60)]
    second = [scene_runner.obstacle_phase(float(second), 810616) for second in range(60)]
    assert first == second
    assert len(set(first)) > 8


def test_pixel_runtime_performs_no_scaling() -> None:
    for name in ("deskbar/ui/scene_train.py", "deskbar/ui/scene_runner.py"):
        source = Path(name).read_text(encoding="utf-8")
        assert "transform." not in source
