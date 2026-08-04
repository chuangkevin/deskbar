from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import planet_horizon, scenes
from deskbar.ui.scene_flow import FlowRenderer, _stream_pose
from deskbar.ui.scene_runtime import SceneFrame


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET_DIR = Path("deskbar/assets/scenes")
NOW = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
PLANET_BASES = tuple(
    f"planet_{layer}_{light}"
    for layer in ("sky", "body", "rim")
    for light in ("night", "dawn", "day")
)
PLANET_OVERLAYS = ("planet_cloud_far", "planet_cloud_near", "planet_haze")
FLOW_ASSETS = (
    "flow_base_night",
    "flow_base_dawn",
    "flow_base_day",
    "flow_filament_veil",
    "flow_brush_0",
    "flow_brush_1",
)


def _render(kind: str, now: datetime, t: float) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    scenes.render(surface, state, now, t, enabled=(kind,), weather_code=1)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _changed_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, dtype=np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, dtype=np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def _render_flow_sequence(times: tuple[float, ...], dt: float) -> bytes:
    renderer = FlowRenderer()
    panel = pygame.Surface((1118, 472))
    for t in times:
        renderer.render(panel, SceneFrame(NOW, t, dt, 1, 810616))
    rendered = pygame.image.tobytes(panel, "RGB")
    renderer.close()
    return rendered


def test_planet_and_flow_assets_meet_dimensions_and_alpha_contracts() -> None:
    # Given / When / Then
    for name in (*PLANET_BASES, *PLANET_OVERLAYS, *FLOW_ASSETS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        alpha = pygame.surfarray.array_alpha(surface)
        if name.startswith(("planet_sky", "flow_base")):
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name


def test_planet_motion_contract_and_body_displacement() -> None:
    # Given
    start = planet_horizon.motion_at(0.0)
    later = planet_horizon.motion_at(15.0)

    # When / Then
    assert abs(start.body_x) <= 16 and abs(later.body_x) <= 16
    assert abs(start.body_y) <= 6 and abs(later.body_y) <= 6
    assert abs(start.far_cloud_x) <= 28 and abs(later.far_cloud_x) <= 28
    assert abs(start.near_cloud_x) <= 48 and abs(later.near_cloud_x) <= 48
    assert 0.92 <= start.rim_alpha <= 1.08
    assert 0.90 <= later.haze_alpha <= 1.10
    assert 2 <= abs(later.body_x - start.body_x) <= 18


def test_planet_and_flow_material_motion_determinism_and_memory() -> None:
    # Given / When / Then
    for kind, minimum_std, minimum_colors, motion_range in (
        ("planet_horizon", 18.0, 180, (0.015, 0.20)),
        ("flow", 12.0, 160, (0.03, 0.35)),
    ):
        first, decoded = _render(kind, NOW, 0.0)
        repeated, repeated_decoded = _render(kind, NOW, 0.0)
        later, _ = _render(kind, NOW, 15.0)
        array = np.frombuffer(first, dtype=np.uint8).reshape(472, 1118, 3)
        sampled = array[::12, ::12].reshape(-1, 3)
        assert first == repeated
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        assert float(array.std()) >= minimum_std
        assert len(np.unique(sampled, axis=0)) >= minimum_colors
        ratio = _changed_ratio(first, later)
        assert motion_range[0] <= ratio <= motion_range[1], (kind, ratio)


def test_planet_lighting_anchors_are_distinct() -> None:
    # Given / When
    frames = [_render("planet_horizon", NOW.replace(hour=hour), 5.0)[0]
              for hour in (3, 7, 12)]

    # Then
    assert len(set(frames)) == 3


def test_flow_frame_is_independent_of_render_history_and_dt() -> None:
    # Given / When
    direct = _render_flow_sequence((15.0,), 1.0 / 20.0)
    sparse = _render_flow_sequence((0.0, 5.0, 15.0), 0.25)
    dense = _render_flow_sequence(
        tuple(index / 20.0 for index in range(301)),
        1.0 / 20.0,
    )

    # Then
    assert direct == sparse == dense


def test_flow_wrap_endpoints_stay_outside_the_visible_crop() -> None:
    # Given / When
    start = _stream_pose(0.0, 1118, 472)
    end = _stream_pose(1.0, 1118, 472)

    # Then
    assert start[0] < -120
    assert end[0] > 1118 + 120
