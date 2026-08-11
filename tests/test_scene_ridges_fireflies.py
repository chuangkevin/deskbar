from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pygame

from deskbar.ui import scenes


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET_DIR = Path("deskbar/assets/scenes")
NOW = datetime(2026, 8, 4, 12, tzinfo=ZoneInfo("Asia/Taipei"))
BASES = tuple(
    f"{scene}_base_{light}"
    for scene in ("ridges", "fireflies")
    for light in ("night", "dawn", "day")
)
OVERLAYS = (
    "ridges_far",
    "ridges_mid",
    "ridges_near",
    "ridges_fog",
    "ridges_shadow",
    "fireflies_grass_far",
    "fireflies_grass_near",
    "fireflies_haze",
    "fireflies_glow_0",
    "fireflies_glow_1",
)


def _render(
    kind: str,
    now: datetime,
    t: float,
    weather_code: int = 1,
) -> tuple[bytes, int]:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    scenes.render(surface, state, now, t, enabled=(kind,), weather_code=weather_code)
    crop = surface.subsurface((402, 8, 1118, 472))
    return pygame.image.tobytes(crop, "RGB"), state["renderer"].decoded_bytes


def _motion_ratio(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    b = np.frombuffer(second, np.uint8).reshape(472, 1118, 3).astype(np.int16)
    return float((np.max(np.abs(a - b), axis=2) > 12).mean())


def _mean_delta(first: bytes, second: bytes) -> float:
    a = np.frombuffer(first, np.uint8).astype(np.int16)
    b = np.frombuffer(second, np.uint8).astype(np.int16)
    return float(np.abs(a - b).mean())


def test_ridge_and_firefly_assets_cover_crop_without_alpha_edges() -> None:
    for name in (*BASES, *OVERLAYS):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        assert surface.get_size() == (1240, 472)
        alpha = pygame.surfarray.array_alpha(surface)
        if "_base_" in name:
            assert alpha.min() == 255
        else:
            edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
            assert edges.max() == 0, name


def test_ridges_and_fireflies_material_motion_lighting_and_memory() -> None:
    for kind, motion_range in (("ridges", (0.0, 0.08)), ("fireflies", (0.01, 0.25))):
        first, decoded = _render(kind, NOW, 0.0)
        repeated, repeated_decoded = _render(kind, NOW, 0.0)
        later, _ = _render(kind, NOW, 15.0)
        array = np.frombuffer(first, np.uint8).reshape(472, 1118, 3)
        sampled = array[::12, ::12].reshape(-1, 3)
        anchors = [_render(kind, NOW.replace(hour=hour), 5.0)[0] for hour in (3, 7, 12)]
        assert first == repeated
        assert first != later
        assert decoded == repeated_decoded
        assert decoded <= 48 * 1024 * 1024
        assert float(array.std()) >= 12.0
        assert len(np.unique(sampled, axis=0)) >= 160
        ratio = _motion_ratio(first, later)
        assert motion_range[0] <= ratio <= motion_range[1], (kind, ratio)
        assert len(set(anchors)) == 3


def test_ridges_weather_materially_changes_atmosphere() -> None:
    clear, _ = _render("ridges", NOW, 8.0, weather_code=0)
    cloudy, _ = _render("ridges", NOW, 8.0, weather_code=3)
    rain, _ = _render("ridges", NOW, 8.0, weather_code=63)
    fog, _ = _render("ridges", NOW, 8.0, weather_code=45)

    assert len({clear, cloudy, rain, fog}) == 4
    assert _mean_delta(clear, cloudy) >= 0.75
    assert _mean_delta(clear, rain) >= 1.5
    assert _mean_delta(clear, fog) >= 2.5
    assert _motion_ratio(clear, rain) >= 0.03
    assert _motion_ratio(clear, fog) >= 0.03


def test_ridges_runtime_has_no_per_frame_smoothscale() -> None:
    source = Path("deskbar/ui/scene_ridges.py").read_text(encoding="utf-8")
    assert "smoothscale" not in source
    assert "BASE_X + offset" not in source


def test_fireflies_quality_contract() -> None:
    # 1. Day vs Night base contrast
    night_render, decoded = _render("fireflies", NOW.replace(hour=3), 0.0)
    day_render, _ = _render("fireflies", NOW.replace(hour=12), 0.0)
    assert _mean_delta(night_render, day_render) >= 15.0

    # 2. Transparent borders on overlays
    for name in (
        "fireflies_grass_far",
        "fireflies_grass_near",
        "fireflies_haze",
        "fireflies_glow_0",
        "fireflies_glow_1",
    ):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        alpha = pygame.surfarray.array_alpha(surface)
        edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
        assert edges.max() == 0, f"Leaking border alpha in {name}"

    # 3. Glow assets have non-transparent glowing content
    for name in ("fireflies_glow_0", "fireflies_glow_1"):
        surface = pygame.image.load(str(ASSET_DIR / f"{name}.png"))
        alpha = pygame.surfarray.array_alpha(surface)
        assert alpha.max() >= 200, f"Weak glow core in {name}"

    # 4. 0/5/15 render determinism, visible motion, decoded bytes
    t0, d0 = _render("fireflies", NOW, 0.0)
    t0_rep, d0_rep = _render("fireflies", NOW, 0.0)
    t5, _ = _render("fireflies", NOW, 5.0)
    t15, _ = _render("fireflies", NOW, 15.0)

    assert t0 == t0_rep
    assert d0 == d0_rep <= 48 * 1024 * 1024
    assert _motion_ratio(t0, t5) >= 0.005
    assert _motion_ratio(t0, t15) >= 0.01
