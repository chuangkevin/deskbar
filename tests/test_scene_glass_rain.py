"""Tests for scene_glass_rain overlay and web setting selectors."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pygame

from deskbar.ui import scene_glass_rain
from deskbar.ui.scene_runtime import SceneFrame

TZ = ZoneInfo("Asia/Taipei")


def test_glass_rain_weather_gating():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)

    # Codes that MUST NOT modify any pixel
    non_rain_codes = [None, 0, 3, 45, 71]
    for code in non_rain_codes:
        panel = pygame.Surface((1118, 472))
        panel.fill((50, 100, 150))
        before = pygame.surfarray.array3d(panel).copy()

        frame = SceneFrame(now=now, t=10.0, dt=0.05, weather_code=code, day_seed=2026100)
        scene_glass_rain.draw(panel, frame)

        after = pygame.surfarray.array3d(panel)
        assert (before == after).all(), f"Weather code {code} must not modify any pixels on panel"

    # Rain and thunder codes that MUST draw droplets
    rain_codes = [61, 95]
    for code in rain_codes:
        panel = pygame.Surface((1118, 472))
        panel.fill((50, 100, 150))
        before = pygame.surfarray.array3d(panel).copy()

        frame = SceneFrame(now=now, t=10.0, dt=0.05, weather_code=code, day_seed=2026100)
        scene_glass_rain.draw(panel, frame)

        after = pygame.surfarray.array3d(panel)
        assert not (before == after).all(), f"Weather code {code} must draw rain overlay pixels"


def test_glass_rain_deterministic_and_bounds():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    frame = SceneFrame(now=now, t=12.5, dt=0.05, weather_code=61, day_seed=2026100)

    panel1 = pygame.Surface((1118, 472))
    panel1.fill((20, 30, 40))
    scene_glass_rain.draw(panel1, frame)
    arr1 = pygame.surfarray.array3d(panel1)

    panel2 = pygame.Surface((1118, 472))
    panel2.fill((20, 30, 40))
    scene_glass_rain.draw(panel2, frame)
    arr2 = pygame.surfarray.array3d(panel2)

    assert (arr1 == arr2).all(), "glass_rain overlay must be 100% deterministic"


def test_web_setting_contains_four_selectors():
    html_path = Path(__file__).resolve().parent.parent / "deskbar" / "web" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    for key, zh_label in (
        ("glass_rain", "玻璃雨"),
        ("magnetic_fog", "磁霧"),
        ("reverse_lightning", "逆閃電"),
        ("tidal_aurora", "潮汐極光"),
    ):
        assert key in content, f"web index.html missing key {key}"
        assert zh_label in content, f"web index.html missing Chinese label {zh_label}"


def test_glass_rain_no_panel_surface_allocation(monkeypatch):
    allocations = []
    real_surface = pygame.Surface

    def tracked_surface(size, *args, **kwargs):
        allocations.append(size)
        return real_surface(size, *args, **kwargs)

    monkeypatch.setattr(scene_glass_rain.pygame, "Surface", tracked_surface)

    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    frame = SceneFrame(now=now, t=10.0, dt=0.05, weather_code=61, day_seed=2026100)
    panel = real_surface((1118, 472))

    allocations.clear()
    scene_glass_rain.draw(panel, frame)

    assert (1118, 472) not in allocations, "draw() must not allocate panel-sized Surface"
    for w, h in allocations:
        assert w * h < 4_096, f"Unexpected large allocation in draw(): ({w}, {h})"



def test_glass_rain_sprite_cache_alpha_edges():
    scene_glass_rain._clear_cache_for_tests()
    sprites = (
        *(scene_glass_rain._drop_sprite(diameter) for diameter in (13, 19, 27)),
        scene_glass_rain._trail_sprite(19),
    )

    for sprite in sprites:
        w, h = sprite.get_size()
        for x in range(w):
            assert sprite.get_at((x, 0))[3] == 0, f"Sprite top edge at x={x} must have alpha==0"
            assert sprite.get_at((x, h - 1))[3] == 0, f"Sprite bottom edge at x={x} must have alpha==0"
        for y in range(h):
            assert sprite.get_at((0, y))[3] == 0, f"Sprite left edge at y={y} must have alpha==0"
            assert sprite.get_at((w - 1, y))[3] == 0, f"Sprite right edge at y={y} must have alpha==0"
