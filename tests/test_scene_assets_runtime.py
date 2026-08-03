from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pygame
import pytest

from deskbar.config import SCENE_KEYS
from deskbar.ui import scenes
from deskbar.ui.scene_assets import (
    DEFAULT_BYTE_LIMIT,
    AssetMemoryLimitError,
    MasterBlend,
    SceneAssets,
    SceneAssetsClosedError,
    TintRequest,
)
from tools.scene_bakers.common import (
    OUTPUT_SIZE,
    WORK_SIZE,
    feather_alpha,
    fbm,
    save_rgba,
    validate_alpha_edges,
)


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()


def _save_fixture(path: Path, color: tuple[int, int, int, int]) -> None:
    surface = pygame.Surface((8, 4), pygame.SRCALPHA)
    surface.fill(color)
    pygame.image.save(surface, path)


def test_scene_assets_load_lazily_cache_and_release(tmp_path: Path) -> None:
    # Given
    _save_fixture(tmp_path / "base.png", (10, 20, 30, 255))
    assets = SceneAssets(tmp_path)
    assert assets.decoded_bytes == 0

    # When
    first = assets.load("base")
    second = assets.load("base")

    # Then
    assert first is second
    assert assets.decoded_bytes == 8 * 4 * 4
    assets.close()
    assert assets.decoded_bytes == 0
    with pytest.raises(SceneAssetsClosedError):
        assets.load("base")


def test_scene_assets_cache_tint_scale_and_master_blend(tmp_path: Path) -> None:
    # Given
    _save_fixture(tmp_path / "night.png", (20, 30, 40, 255))
    _save_fixture(tmp_path / "day.png", (220, 230, 240, 255))
    assets = SceneAssets(tmp_path)
    tint = TintRequest("night", (128, 200, 255), (4, 2))
    blend = MasterBlend("night", "day", 0.5)

    # When / Then
    assert assets.tinted(tint) is assets.tinted(tint)
    assert assets.blended(blend) is assets.blended(blend)
    assert assets.decoded_bytes > 0


def test_scene_assets_reject_decoded_memory_overflow(tmp_path: Path) -> None:
    # Given
    _save_fixture(tmp_path / "base.png", (10, 20, 30, 255))
    assets = SceneAssets(tmp_path, byte_limit=1)

    # When / Then
    with pytest.raises(AssetMemoryLimitError):
        assets.load("base")
    assert assets.decoded_bytes == 0


def test_common_baker_noise_and_png_saves_are_deterministic(tmp_path: Path) -> None:
    # Given
    first_noise = fbm(64, 32, seed=41)
    second_noise = fbm(64, 32, seed=41)
    width, height = WORK_SIZE
    rgba = np.zeros((height, width, 4), dtype=np.float32)
    rgba[..., 0] = first_noise.mean()
    rgba[..., 1] = 0.4
    rgba[..., 2] = 0.7
    rgba[..., 3] = 1.0
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"

    # When
    save_rgba(first_path, rgba, transparent=False)
    save_rgba(second_path, rgba, transparent=False)

    # Then
    assert np.array_equal(first_noise, second_noise)
    assert first_path.read_bytes() == second_path.read_bytes()
    surface = pygame.image.load(str(first_path))
    assert surface.get_size() == OUTPUT_SIZE
    assert pygame.surfarray.array_alpha(surface).min() == 255


def test_common_baker_feathers_overlay_edges_and_rejects_leaks(tmp_path: Path) -> None:
    # Given
    width, height = WORK_SIZE
    rgba = np.ones((height, width, 4), dtype=np.float32)
    rgba[..., 3] = feather_alpha(rgba[..., 3], border_x=64, border_y=32)
    overlay_path = tmp_path / "overlay.png"

    # When
    save_rgba(overlay_path, rgba, transparent=True)

    # Then
    validate_alpha_edges(overlay_path)
    leaking = pygame.Surface(OUTPUT_SIZE, pygame.SRCALPHA)
    leaking.fill((255, 255, 255, 255))
    leak_path = tmp_path / "leak.png"
    pygame.image.save(leaking, leak_path)
    with pytest.raises(ValueError, match="alpha border"):
        validate_alpha_edges(leak_path)


def test_each_active_scene_stays_within_decoded_asset_limit() -> None:
    # Given
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()

    # When / Then
    for index, kind in enumerate(SCENE_KEYS):
        previous = state.get("renderer")
        scenes.render(surface, state, datetime(2026, 8, 4, 12), 10.0 + index,
                      enabled=[kind])
        if previous is not None:
            assert previous.closed
            assert previous.decoded_bytes == 0
        assert state["renderer"].decoded_bytes <= DEFAULT_BYTE_LIMIT


def test_runtime_scene_modules_do_not_use_offline_pixel_tools() -> None:
    # Given
    paths = [*Path("deskbar/ui").glob("scene*.py"), Path("deskbar/ui/planet_horizon.py")]

    # When
    sources = {path: path.read_text(encoding="utf-8") for path in paths}

    # Then
    for path, source in sources.items():
        assert "import numpy" not in source, path
        assert "pygame.surfarray" not in source, path
