from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import scene_fish, scenes
from deskbar.ui.scene_ink import InkRenderer
from deskbar.ui.scene_runtime import SceneFrame


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET_DIR = Path("deskbar/assets/scenes")
NOW = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
BASES = tuple(
    f"{scene}_base_{light}"
    for scene in ("fish", "ink")
    for light in ("night", "dawn", "day")
)
OVERLAYS = (
    "fish_sprite_0",
    "fish_sprite_1",
    "fish_sprite_2",
    "fish_wake_0",
    "fish_wake_1",
    "ink_bloom_0",
    "ink_bloom_1",
    "ink_bloom_2",
)


def _render(kind: str, now: datetime, t: float, weather: int = 1) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    scenes.render(surface, state, now, t, enabled=(kind,), weather_code=weather)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _motion_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def test_fish_and_ink_assets_have_authored_canvas_and_clean_edges() -> None:
    for name in (*BASES, *OVERLAYS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        alpha = pygame.surfarray.array_alpha(surface)
        if "_base_" in name:
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name


def test_fish_sprites_have_top_down_vertical_silhouettes() -> None:
    fish_rects = (
        (138, 71, 220, 330),
        (510, 71, 220, 330),
        (882, 71, 220, 330),
    )
    for frame in range(3):
        alpha = pygame.surfarray.array_alpha(
            pygame.image.load(str(ASSET_DIR / f"fish_sprite_{frame}.png"))
        )
        for x, y, width, height in fish_rects:
            visible = np.argwhere(alpha[x:x + width, y:y + height] > 8)
            assert np.ptp(visible[:, 1]) > np.ptp(visible[:, 0]) * 1.35


def test_fish_visibility_and_wake_contracts_at_key_times() -> None:
    base_day = pygame.image.load(str(ASSET_DIR / "fish_base_day.png"))
    base_night = pygame.image.load(str(ASSET_DIR / "fish_base_night.png"))
    diff = np.abs(
        pygame.surfarray.array3d(base_day).astype(np.int16)
        - pygame.surfarray.array3d(base_night).astype(np.int16)
    )
    assert float(diff.mean()) > 30.0

    for wake_name in ("fish_wake_0", "fish_wake_1"):
        alpha = pygame.surfarray.array_alpha(
            pygame.image.load(str(ASSET_DIR / f"{wake_name}.png"))
        )
        assert alpha.max() > 100
        edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
        assert edges.max() == 0

    for t_sec in (0.0, 5.0, 15.0):
        frame_bytes, decoded_bytes = _render("fish", NOW, t_sec)
        assert decoded_bytes <= 48 * 1024 * 1024
        frame_arr = np.frombuffer(frame_bytes, np.uint8).reshape(472, 1118, 3)
        thirds = (
            frame_arr[:, :372, :],
            frame_arr[:, 372:744, :],
            frame_arr[:, 744:, :],
        )
        high_variance_count = sum(float(part.std()) > 15.0 for part in thirds)
        assert high_variance_count >= 2

        for x, y in scene_fish.fish_positions(t_sec, 1118, 472):
            assert 90.0 <= x <= 1028.0
            assert 90.0 <= y <= 382.0


def test_ink_runtime_source_tiles_have_no_alpha_at_crop_bounds() -> None:
    for index in range(3):
        surface = pygame.image.load(str(ASSET_DIR / f"ink_bloom_{index}.png"))
        tile = pygame.surfarray.array_alpha(surface)[460:780, 76:396]
        border = np.concatenate((tile[:4, :].ravel(), tile[-4:, :].ravel(),
                                 tile[:, :4].ravel(), tile[:, -4:].ravel()))
        assert border.max() == 0, index


def test_fish_and_ink_material_motion_lighting_determinism_and_memory() -> None:
    for kind, motion_range in (("fish", (0.015, 0.28)), ("ink", (0.02, 0.35))):
        first, decoded = _render(kind, NOW, 0.0)
        repeated, repeated_decoded = _render(kind, NOW, 0.0)
        later, _ = _render(kind, NOW, 15.0)
        array = np.frombuffer(first, np.uint8).reshape(472, 1118, 3)
        sampled = array[::12, ::12].reshape(-1, 3)
        anchors = [_render(kind, NOW.replace(hour=hour), 5.0)[0] for hour in (3, 7, 12)]
        assert first == repeated
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        assert float(array.std()) >= 12.0
        assert len(np.unique(sampled, axis=0)) >= 160
        ratio = _motion_ratio(first, later)
        assert motion_range[0] <= ratio <= motion_range[1], (kind, ratio)
        assert len(set(anchors)) == 3


def test_fish_weather_changes_swimming_depth() -> None:
    sunny, _ = _render("fish", NOW, 8.0, weather=1)
    rainy, _ = _render("fish", NOW, 8.0, weather=65)
    assert sunny != rainy


def test_ink_quantized_cache_is_bounded() -> None:
    renderer = InkRenderer()
    panel = pygame.Surface((1118, 472))
    for second in range(0, 40):
        renderer.render(
            panel,
            SceneFrame(NOW, float(second), 0.1, 1, 810616),
        )
    assert renderer.scaled_cache_entries <= 24
    assert renderer.decoded_bytes <= 48 * 1024 * 1024
    renderer.close()
    assert renderer.decoded_bytes == 0
