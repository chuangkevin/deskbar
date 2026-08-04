from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import scene_stars, scenes


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET_DIR = Path("deskbar/assets/scenes")
NOW = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
BASES = tuple(
    f"{scene}_base_{light}"
    for scene in ("stars", "aurora")
    for light in ("night", "dawn", "day")
)
OVERLAYS = (
    "stars_dust_far",
    "stars_dust_near",
    "stars_sprite_0",
    "stars_sprite_1",
    "stars_sprite_2",
    "stars_meteor",
    "aurora_curtain_0",
    "aurora_curtain_1",
    "aurora_curtain_2",
)


def _render(kind: str, now: datetime, t: float) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    scenes.render(surface, state, now, t, enabled=(kind,), weather_code=1)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _motion_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def test_stars_and_aurora_asset_contracts() -> None:
    for name in (*BASES, *OVERLAYS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        alpha = pygame.surfarray.array_alpha(surface)
        if "_base_" in name:
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name
        if name.startswith("aurora_curtain_"):
            rgb = pygame.surfarray.array3d(surface)
            alpha_seam = np.abs(alpha[61].astype(np.int16) - alpha[1178].astype(np.int16))
            rgb_seam = np.abs(rgb[61].astype(np.int16) - rgb[1178].astype(np.int16))
            assert float(alpha_seam.mean()) <= 2.0, name
            assert float(rgb_seam.mean()) <= 5.0, name


def test_stars_meteor_schedule_is_deterministic_and_rare() -> None:
    first = [scene_stars.meteor_active(float(second), 810616) for second in range(240)]
    second = [scene_stars.meteor_active(float(second), 810616) for second in range(240)]
    assert first == second
    assert any(first)
    assert sum(first) < len(first) // 8


def test_stars_and_aurora_material_motion_lighting_and_memory() -> None:
    for kind, motion_range in (("stars", (0.005, 0.18)), ("aurora", (0.02, 0.32))):
        first, decoded = _render(kind, NOW, 0.0)
        repeated, repeated_decoded = _render(kind, NOW, 0.0)
        motion_now = NOW.replace(hour=3) if kind == "aurora" else NOW
        motion_first, _ = _render(kind, motion_now, 0.0)
        later, _ = _render(kind, motion_now, 15.0)
        array = np.frombuffer(first, np.uint8).reshape(472, 1118, 3)
        sampled = array[::12, ::12].reshape(-1, 3)
        anchors = [_render(kind, NOW.replace(hour=hour), 5.0)[0] for hour in (3, 7, 12)]
        assert first == repeated
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        assert float(array.std()) >= 12.0
        assert len(np.unique(sampled, axis=0)) >= 160
        ratio = _motion_ratio(motion_first, later)
        assert motion_range[0] <= ratio <= motion_range[1], (kind, ratio)
        assert len(set(anchors)) == (1 if kind == "aurora" else 3)


def test_aurora_uses_night_lighting_at_all_hours() -> None:
    night, _ = _render("aurora", NOW.replace(hour=3), 15.0)
    dawn, _ = _render("aurora", NOW.replace(hour=7), 15.0)
    day, _ = _render("aurora", NOW, 15.0)
    assert night == dawn == day
