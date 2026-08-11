from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import scene_runner, scene_train, scenes


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


def _render_progressed_runner(seconds: float) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    for frame in range(round(seconds * 20) + 1):
        scenes.render(surface, state, NOW, frame / 20.0, enabled=("runner",), weather_code=1)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _motion_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def test_train_and_runner_assets_use_authored_canvas_and_clean_edges() -> None:
    for name in (*BASES, *OVERLAYS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        rgb = pygame.surfarray.array3d(surface)
        if name.startswith("runner_"):
            assert np.array_equal(rgb[0::2, 0::2], rgb[1::2, 0::2]), name
            assert np.array_equal(rgb[0::2, 0::2], rgb[0::2, 1::2]), name
        alpha = pygame.surfarray.array_alpha(surface)
        if "_base_" in name:
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name


def test_train_uses_antialiased_scaling_instead_of_2x2_pixel_blocks() -> None:
    rgb = pygame.surfarray.array3d(
        pygame.image.load(str(ASSET_DIR / "train_near.png"))
    )
    assert not np.array_equal(rgb[0::2, 0::2], rgb[1::2, 0::2])


def test_train_lighting_tracks_local_date_and_subminute_time() -> None:
    night = scene_train._lighting(datetime(2026, 8, 4, 2, tzinfo=ZoneInfo("Asia/Taipei")))
    day = scene_train._lighting(datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei")))
    dawn_first = scene_train._lighting(
        datetime(2026, 8, 4, 5, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    dawn_later = scene_train._lighting(
        datetime(2026, 8, 4, 5, 0, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    assert night == ("night", "night", 0.0)
    assert day == ("day", "day", 0.0)
    assert dawn_first[:2] == dawn_later[:2] == ("night", "dawn")
    assert dawn_later[2] > dawn_first[2]


def test_train_layers_cover_and_repeat_at_authored_cycle() -> None:
    for name in ("train_far", "train_mid", "train_near"):
        layer = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        first = pygame.Surface((1118, 472), pygame.SRCALPHA)
        repeated = pygame.Surface((1118, 472), pygame.SRCALPHA)
        scene_train._blit_wrapped(first, layer, 0.0)
        scene_train._blit_wrapped(repeated, layer, float(scene_train.TILE_PERIOD))
        assert pygame.image.tobytes(first, "RGBA") == pygame.image.tobytes(repeated, "RGBA")

    for distance in (0.0, scene_train.TILE_PERIOD / 2, scene_train.TILE_PERIOD - 1.0):
        layer = pygame.image.load(str(ASSET_DIR / "train_near.png"))
        tiled = pygame.Surface((1118, 472), pygame.SRCALPHA)
        scene_train._blit_wrapped(tiled, layer, distance)
        assert pygame.surfarray.array_alpha(tiled)[:, 420].min() > 0


def test_train_foreground_moves_on_every_20fps_frame() -> None:
    frames = [_render("train", frame / 20.0)[0] for frame in range(4)]
    arrays = [
        np.frombuffer(frame, np.uint8).reshape(472, 1118, 3)[320:450]
        for frame in frames
    ]
    ratios = [
        float((np.max(np.abs(first.astype(np.int16) - second), axis=2) > 12).mean())
        for first, second in zip(arrays, arrays[1:])
    ]
    assert min(ratios) >= 0.02, ratios


def test_train_and_runner_palette_motion_determinism_and_memory() -> None:
    for kind in ("train", "runner"):
        first, decoded = _render(kind, 0.0)
        repeated, repeated_decoded = _render(kind, 0.0)
        later, _ = _render_progressed_runner(5.0) if kind == "runner" else _render(kind, 15.0)
        array = np.frombuffer(first, np.uint8).reshape(472, 1118, 3)
        sampled = array[::8, ::8].reshape(-1, 3)
        assert first == repeated
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        color_count = len(np.unique(sampled, axis=0))
        assert color_count >= 40
        ratio = _motion_ratio(first, later)
        assert 0.05 <= ratio <= 0.45, (kind, ratio)


def test_train_quality_contract_depth_texture_and_three_time_periods() -> None:
    """Verify train scene quality contract: 3 time of day profiles, layer depth/texture, seam-conscious tiling, determinism, and memory <= 48MiB."""
    surface_night = pygame.Surface((1920, 480))
    state_night = scenes.new_state()
    now_night = datetime(2026, 8, 4, 2, tzinfo=ZoneInfo("Asia/Taipei"))
    scenes.render(surface_night, state_night, now_night, 0.0, enabled=("train",), weather_code=1)
    night_bytes = pygame.image.tobytes(surface_night.subsurface((402, 8, 1118, 472)), "RGB")

    surface_dawn = pygame.Surface((1920, 480))
    state_dawn = scenes.new_state()
    now_dawn = datetime(2026, 8, 4, 5, 0, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    scenes.render(surface_dawn, state_dawn, now_dawn, 0.0, enabled=("train",), weather_code=1)
    dawn_bytes = pygame.image.tobytes(surface_dawn.subsurface((402, 8, 1118, 472)), "RGB")

    surface_day = pygame.Surface((1920, 480))
    state_day = scenes.new_state()
    now_day = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
    scenes.render(surface_day, state_day, now_day, 0.0, enabled=("train",), weather_code=1)
    day_bytes = pygame.image.tobytes(surface_day.subsurface((402, 8, 1118, 472)), "RGB")

    assert _motion_ratio(night_bytes, day_bytes) > 0.10
    assert _motion_ratio(dawn_bytes, day_bytes) > 0.05
    assert _motion_ratio(night_bytes, dawn_bytes) > 0.05

    near_img = pygame.image.load(str(ASSET_DIR / "train_near.png"))
    mid_img = pygame.image.load(str(ASSET_DIR / "train_mid.png"))
    far_img = pygame.image.load(str(ASSET_DIR / "train_far.png"))

    near_rgb = pygame.surfarray.array3d(near_img)
    mid_rgb = pygame.surfarray.array3d(mid_img)
    far_rgb = pygame.surfarray.array3d(far_img)

    assert near_rgb.std() > 25.0
    assert mid_rgb.std() > 20.0
    assert far_rgb.std() > 15.0

    for layer in (near_img, mid_img, far_img):
        surf_start = pygame.Surface((1118, 472), pygame.SRCALPHA)
        surf_tile = pygame.Surface((1118, 472), pygame.SRCALPHA)
        scene_train._blit_wrapped(surf_start, layer, 0.0)
        scene_train._blit_wrapped(surf_tile, layer, float(scene_train.TILE_PERIOD))
        assert pygame.image.tobytes(surf_start, "RGBA") == pygame.image.tobytes(surf_tile, "RGBA")

    render1, bytes1 = _render("train", 2.5)
    render2, bytes2 = _render("train", 2.5)
    assert render1 == render2
    assert bytes1 == bytes2 <= 48 * 1024 * 1024


def test_runner_lighting_and_day_night_render_difference() -> None:
    night = scene_runner._lighting(datetime(2026, 8, 4, 2, tzinfo=ZoneInfo("Asia/Taipei")))
    day = scene_runner._lighting(datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei")))
    dawn_first = scene_runner._lighting(
        datetime(2026, 8, 4, 5, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    )
    dawn_later = scene_runner._lighting(
        datetime(2026, 8, 4, 5, 0, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    )

    assert night == ("night", "night", 0.0)
    assert day == ("day", "day", 0.0)
    assert dawn_first[:2] == dawn_later[:2] == ("night", "dawn")
    assert dawn_later[2] > dawn_first[2]

    surface_day = pygame.Surface((1920, 480))
    state_day = scenes.new_state()
    now_day = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
    scenes.render(surface_day, state_day, now_day, 0.0, enabled=("runner",), weather_code=1)
    day_bytes = pygame.image.tobytes(surface_day.subsurface((402, 8, 1118, 472)), "RGB")

    surface_night = pygame.Surface((1920, 480))
    state_night = scenes.new_state()
    now_night = datetime(2026, 8, 4, 2, tzinfo=ZoneInfo("Asia/Taipei"))
    scenes.render(surface_night, state_night, now_night, 0.0, enabled=("runner",), weather_code=1)
    night_bytes = pygame.image.tobytes(surface_night.subsurface((402, 8, 1118, 472)), "RGB")

    assert day_bytes != night_bytes
    assert _motion_ratio(day_bytes, night_bytes) > 0.05


def test_runner_bases_have_sufficient_difference() -> None:
    night_img = pygame.surfarray.array3d(pygame.image.load(str(ASSET_DIR / "runner_base_night.png")))
    dawn_img = pygame.surfarray.array3d(pygame.image.load(str(ASSET_DIR / "runner_base_dawn.png")))
    day_img = pygame.surfarray.array3d(pygame.image.load(str(ASSET_DIR / "runner_base_day.png")))

    assert float(np.mean(np.abs(night_img.astype(np.int16) - day_img.astype(np.int16)))) > 20.0
    assert float(np.mean(np.abs(dawn_img.astype(np.int16) - day_img.astype(np.int16)))) > 10.0
    assert float(np.mean(np.abs(night_img.astype(np.int16) - dawn_img.astype(np.int16)))) > 10.0


def test_runner_cannot_pass_through_pipe() -> None:
    pipe_x, _height = scene_runner.PIPES[0]
    state = scene_runner.RunnerState(x=pipe_x - scene_runner.PLAYER_WIDTH - 2)
    scene_runner.advance_runner(state, 0.2, auto_jump=False)
    assert state.x == pipe_x - scene_runner.PLAYER_WIDTH
    assert state.phase == "running"


def test_runner_side_collision_with_enemy_causes_death_and_reset() -> None:
    state = scene_runner.RunnerState()
    enemy = state.enemies[0]
    state.x = enemy.x - scene_runner.PLAYER_WIDTH + 4
    scene_runner.advance_runner(state, 0.05, auto_jump=False)
    assert state.phase == "dead"
    assert state.deaths == 1

    for _ in range(120):
        scene_runner.advance_runner(state, 1 / 60, auto_jump=False)
    assert state.phase == "running"
    assert state.x < 200
    assert state.y == scene_runner.GROUND_Y - scene_runner.PLAYER_HEIGHT


def test_runner_stomps_enemy_and_bounces() -> None:
    state = scene_runner.RunnerState(on_ground=False)
    enemy = state.enemies[0]
    state.x = enemy.x
    state.y = scene_runner.GROUND_Y - 32 - scene_runner.PLAYER_HEIGHT - 3
    state.vy = 180.0
    scene_runner.advance_runner(state, 0.05, auto_jump=False)
    assert not enemy.alive
    assert state.phase == "running"
    assert state.vy < 0


def test_runner_hits_question_block_from_below() -> None:
    block_x, block_y, _kind = scene_runner.BLOCKS[1]
    state = scene_runner.RunnerState(
        x=float(block_x),
        y=float(block_y + 34),
        vy=-260.0,
        on_ground=False,
    )
    scene_runner.advance_runner(state, 0.05, auto_jump=False)
    assert 1 in state.used_blocks
    assert state.y >= block_y + 32
    assert state.vy >= 0.0


def test_runner_auto_player_completes_entire_level() -> None:
    state = scene_runner.RunnerState()
    for _ in range(60 * 40):
        scene_runner.advance_runner(state, 1 / 60)
    assert state.finishes == 1
    assert state.deaths == 0


def test_pixel_runtime_performs_no_scaling() -> None:
    for name in ("deskbar/ui/scene_train.py", "deskbar/ui/scene_runner.py"):
        source = Path(name).read_text(encoding="utf-8")
        assert "transform." not in source
