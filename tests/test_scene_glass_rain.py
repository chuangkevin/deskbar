"""Behaviour and performance contracts for the scene rain-on-glass layer."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pygame

from deskbar.ui import scene_glass_rain
from deskbar.ui.scene_runtime import SceneFrame


TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)


def _frame(code=61, t=10.0, seed=2026100):
    return SceneFrame(
        now=NOW, t=t, dt=0.05, weather_code=code, day_seed=seed
    )


def test_glass_rain_weather_gating():
    for code in (None, 0, 3, 45, 71):
        panel = pygame.Surface((1118, 472))
        panel.fill((50, 100, 150))
        before = pygame.image.tobytes(panel, "RGB")
        scene_glass_rain.draw(panel, _frame(code))
        assert pygame.image.tobytes(panel, "RGB") == before
    for code in (51, 61, 95):
        panel = pygame.Surface((1118, 472))
        panel.fill((50, 100, 150))
        before = pygame.image.tobytes(panel, "RGB")
        scene_glass_rain.draw(panel, _frame(code))
        assert pygame.image.tobytes(panel, "RGB") != before


def test_glass_rain_is_deterministic():
    first = pygame.Surface((1118, 472))
    second = pygame.Surface((1118, 472))
    first.fill((20, 30, 40))
    second.fill((20, 30, 40))
    scene_glass_rain.draw(first, _frame(t=12.5))
    scene_glass_rain.draw(second, _frame(t=12.5))
    assert pygame.image.tobytes(first, "RGB") == pygame.image.tobytes(second, "RGB")


def test_web_setting_contains_four_selectors():
    html = (Path(__file__).parent.parent / "deskbar" / "web" / "index.html").read_text()
    for key, label in (
        ("glass_rain", "玻璃雨"), ("magnetic_fog", "磁霧"),
        ("reverse_lightning", "逆閃電"), ("tidal_aurora", "潮汐極光"),
    ):
        assert key in html
        assert label in html


def test_variant_space_is_diverse_small_and_bounded():
    assert len(scene_glass_rain._FIXED_KEYS) >= 10
    assert max(key[0] for key in scene_glass_rain._FIXED_KEYS) <= 14
    assert max(key[1] for key in scene_glass_rain._FIXED_KEYS) <= 18
    selected = [scene_glass_rain._fixed_key(2026100, index) for index in range(400)]
    assert len(set(selected)) >= 10
    assert sum(key[0] <= 9 for key in selected) / len(selected) >= 0.80
    scene_glass_rain._clear_cache_for_tests()
    for key in scene_glass_rain._ALL_KEYS:
        scene_glass_rain._drop_sprite(key)
        scene_glass_rain._alpha_mask(key)
    assert len(scene_glass_rain._DROP_SPRITE_CACHE) == scene_glass_rain._MAX_CACHE_SIZE
    assert len(scene_glass_rain._ALPHA_MASK_CACHE) == scene_glass_rain._MAX_CACHE_SIZE


def test_variant_edges_are_fully_transparent():
    for key in scene_glass_rain._ALL_KEYS:
        sprite = scene_glass_rain._drop_sprite(key)
        width, height = sprite.get_size()
        assert all(sprite.get_at((x, 0)).a == 0 for x in range(width))
        assert all(sprite.get_at((x, height - 1)).a == 0 for x in range(width))
        assert all(sprite.get_at((0, y)).a == 0 for y in range(height))
        assert all(sprite.get_at((width - 1, y)).a == 0 for y in range(height))


def test_weather_population_and_surface_tension_ratio():
    drizzle = scene_glass_rain._population(52)
    rain = scene_glass_rain._population(61)
    thunder = scene_glass_rain._population(95)
    assert drizzle[0] < rain[0] < thunder[0]
    assert drizzle[1] <= 2
    assert rain[1] <= 4
    assert thunder[1] <= 5
    for fixed, sliding, _ in (drizzle, rain, thunder):
        assert fixed / (fixed + sliding) >= 0.90


def test_larger_drops_have_higher_terminal_velocity():
    small = scene_glass_rain._SLIDING_KEYS[0]
    large = scene_glass_rain._SLIDING_KEYS[-1]
    small_v = [scene_glass_rain._terminal_velocity(small, 1.0, 11, i) for i in range(30)]
    large_v = [scene_glass_rain._terminal_velocity(large, 1.0, 11, i) for i in range(30)]
    assert sum(large_v) / len(large_v) > sum(small_v) / len(small_v)


def test_sliding_motion_is_continuous_accelerating_and_curved():
    key = scene_glass_rain._SLIDING_KEYS[2]
    # Find an active instant, then sample the continuous motion over short steps.
    active_t = next(
        t / 10 for t in range(400)
        if scene_glass_rain._sliding_state(t / 10, 22, 100, key, 1.0, 1118, 472)[3]
    )
    states = [
        scene_glass_rain._sliding_state(active_t + step * 0.05, 22, 100, key, 1.0, 1118, 472)
        for step in range(5)
    ]
    distances = [state[4] for state in states]
    assert distances == sorted(distances)
    assert max(b - a for a, b in zip(distances, distances[1:])) < 8.0
    start_y = states[0][2]
    xs = [scene_glass_rain._path_x(22, 100, y, start_y, 300.0) for y in range(20, 420, 20)]
    assert 3.0 < max(xs) - min(xs) < 15.0


def test_trail_is_short_faint_and_locally_allocated(monkeypatch):
    assert scene_glass_rain._MAX_TRAIL_LENGTH <= 42
    assert scene_glass_rain._MAX_TRAIL_ALPHA <= 45
    allocations = []
    real_surface = pygame.Surface

    def tracked(size, *args, **kwargs):
        allocations.append(size)
        return real_surface(size, *args, **kwargs)

    monkeypatch.setattr(scene_glass_rain.pygame, "Surface", tracked)
    panel = real_surface((1118, 472))
    scene_glass_rain.draw(panel, _frame(95, t=14.0))
    assert (1118, 472) not in allocations
    assert all(width * height < 10_000 for width, height in allocations)


def test_refraction_uses_background_without_numpy_runtime():
    source = Path(scene_glass_rain.__file__).read_text()
    assert "surfarray" not in source
    assert "pixels3d" not in source
    panel = pygame.Surface((160, 100))
    for x in range(160):
        color = (215, 45, 65) if (x // 6) % 2 else (35, 185, 140)
        pygame.draw.line(panel, color, (x, 0), (x, 99))
    before = pygame.image.tobytes(panel, "RGB")
    key = scene_glass_rain._SLIDING_KEYS[-1]
    scene_glass_rain._draw_refracted_drop(panel, key, 80, 50, 48)
    after = pygame.image.tobytes(panel, "RGB")
    assert after != before
    # The lens must still contain both underlying colour families, rather than
    # becoming a flat cyan icon.
    colors = {panel.get_at((x, y))[:3] for x in range(68, 93) for y in range(33, 68)}
    assert any(red > green for red, green, _ in colors)
    assert any(green > red for red, green, _ in colors)
