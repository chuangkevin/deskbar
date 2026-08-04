"""Sense weather-character depth and occlusion regression tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import dashboard, flipclock, sensewx, theme
from deskbar.weather import Weather


NOW = datetime(2026, 8, 3, 16, 55, tzinfo=ZoneInfo("Asia/Taipei"))


def test_clear_day_celestial_stays_behind_opaque_flip_cards():
    # Given: a clear-day sun whose authored position overlaps the center clock cards
    state = AppState()
    state.set_weather(Weather(33.0, 0, 34.0, 26.0, "台北", NOW))
    settings = Settings()
    previous_theme = theme.current_theme()
    theme.set_theme("dark")
    try:
        clock_only = pygame.Surface((400, 480))
        clock_only.fill(theme.C["bg"])
        flipclock.draw(clock_only, sensewx.CLOCK.x, sensewx.CLOCK.y, NOW.strftime("%H:%M"),
                       NOW.strftime("%H:%M"), 1.0, digit_h=96)

        # When: the real sunny left panel is rendered
        sunny_panel = pygame.Surface((400, 480))
        dashboard.render_panel_only(sunny_panel, state.snapshot(), settings, NOW,
                                    weather_t=50.0)

        # Then: every opaque card interior occludes the physically distant sun
        assert sensewx.CLOCK.centerx == 200
        for x in (42, 119, 212, 289):
            interior = pygame.Rect(x + 8, 50, 53, 64)
            expected = pygame.image.tobytes(clock_only.subsurface(interior), "RGB")
            actual = pygame.image.tobytes(sunny_panel.subsurface(interior), "RGB")
            assert actual == expected, "天體不得覆蓋實體翻牌卡或數字"
    finally:
        theme.set_theme(previous_theme)
