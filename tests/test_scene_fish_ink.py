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


def test_ink_rework_quality_and_contract_specifications() -> None:
    """Validate ink scene quality contracts across time periods, background texture, and bloom shapes."""
    night_img = pygame.image.load(str(ASSET_DIR / "ink_base_night.png"))
    dawn_img = pygame.image.load(str(ASSET_DIR / "ink_base_dawn.png"))
    day_img = pygame.image.load(str(ASSET_DIR / "ink_base_day.png"))

    night_rgb = pygame.surfarray.array3d(night_img).astype(np.float32)
    dawn_rgb = pygame.surfarray.array3d(dawn_img).astype(np.float32)
    day_rgb = pygame.surfarray.array3d(day_img).astype(np.float32)

    # 1. Distinct time period palettes and luminance contrast
    assert float(night_rgb.mean()) < 60.0
    assert float(day_rgb.mean()) > 160.0

    diff_night_dawn = float(np.abs(night_rgb - dawn_rgb).mean())
    diff_dawn_day = float(np.abs(dawn_rgb - day_rgb).mean())
    diff_night_day = float(np.abs(night_rgb - day_rgb).mean())

    assert diff_night_dawn > 25.0
    assert diff_dawn_day > 25.0
    assert diff_night_day > 50.0

    # Dawn: Rose/pink/gold warmth (Red channel dominant over Blue)
    assert float(dawn_rgb[:, :, 0].mean()) > float(dawn_rgb[:, :, 2].mean()) + 8.0

    # Night: Indigo blue tone (Blue channel dominant over Red)
    assert float(night_rgb[:, :, 2].mean()) > float(night_rgb[:, :, 0].mean()) + 4.0

    # Day: Cinnabar red point accents exist (high red, low green/blue in accent regions)
    cinnabar_spots = (day_rgb[:, :, 0] > 180) & (day_rgb[:, :, 1] < 100) & (day_rgb[:, :, 2] < 90)
    assert 30 < int(cinnabar_spots.sum()) < 2000

    # 2. Rich background texture, depth variance, and 3x3 spatial grid coverage
    for name, arr in (("night", night_rgb), ("dawn", dawn_rgb), ("day", day_rgb)):
        assert float(arr.std()) > 10.0, name

        # 1118x472 crop region: [61:1179, 0:472]
        crop = arr[61:1179, 0:472, :]
        grid_w, grid_h = 1118 // 3, 472 // 3
        high_std_cells = 0
        for gx in range(3):
            for gy in range(3):
                cell = crop[gx * grid_w:(gx + 1) * grid_w, gy * grid_h:(gy + 1) * grid_h, :]
                if float(cell.std()) >= 5.0:
                    high_std_cells += 1
        assert high_std_cells >= 7, f"{name} base 3x3 grid failed non-monotone coverage: {high_std_cells}/9 cells"

    # Multi-scale Xuan paper texture (high-frequency grain vs base wash)
    smooth_day = (
        day_rgb
        + np.roll(day_rgb, 1, axis=0)
        + np.roll(day_rgb, -1, axis=0)
        + np.roll(day_rgb, 1, axis=1)
        + np.roll(day_rgb, -1, axis=1)
    ) / 5.0
    hf_grain = float(np.abs(day_rgb - smooth_day).mean())
    assert hf_grain > 0.3

    # 3. Organic, non-geometric pigment bloom shape verification (multi-cluster composition)
    for index in range(3):
        bloom_img = pygame.image.load(str(ASSET_DIR / f"ink_bloom_{index}.png"))
        alpha = pygame.surfarray.array_alpha(bloom_img)
        assert alpha.max() > 150

        # Subsurface crop [460:780, 76:396] (320x320)
        tile_alpha = alpha[460:780, 76:396]
        border = np.concatenate((tile_alpha[:4, :].ravel(), tile_alpha[-4:, :].ravel(),
                                 tile_alpha[:, :4].ravel(), tile_alpha[:, -4:].ravel()))
        assert border.max() == 0, index

        # Find local peaks in 320x320 crop tile to verify multi-cluster structure
        # Downsample to 16x16 grid for robust cluster peak counting
        grid_peaks = 0
        grid = tile_alpha.reshape(16, 20, 16, 20).mean(axis=(1, 3))
        for gx in range(1, 15):
            for gy in range(1, 15):
                val = grid[gx, gy]
                if val > 40:
                    neighbors = grid[gx - 1:gx + 2, gy - 1:gy + 2]
                    if val >= neighbors.max():
                        grid_peaks += 1
        assert grid_peaks >= 2, f"bloom {index} must have at least 2 distinct clusters, got {grid_peaks}"

        # Sample radii at 16 angles from center to confirm non-circular/non-regular shape
        cx, cy = 620, 236
        radii = []
        for angle_deg in range(0, 360, 22):
            rad = np.radians(angle_deg)
            dx, dy = np.cos(rad), np.sin(rad)
            r = 0
            while r < 230:
                px, py = int(cx + r * dx), int(cy + r * dy)
                if px < 0 or px >= 1240 or py < 0 or py >= 472:
                    break
                if alpha[px, py] < 20 and r > 60:
                    break
                r += 2
            radii.append(r)

        radii_arr = np.array(radii, dtype=np.float32)
        shape_irregularity = float(radii_arr.std() / (radii_arr.mean() + 1e-5))
        assert shape_irregularity > 0.08, f"bloom {index} is too geometric: {shape_irregularity}"
