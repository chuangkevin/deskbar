"""行星地平線場景的素材、設定與 headless 渲染契約。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.ui import scenes


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
def test_planet_horizon_renders_distinct_dawn_day_and_night_frames():
    # Given: the same selected cinematic scene at three real-world times
    # When: each frame is rendered headlessly
    # Then: time changes the authored lighting rather than applying one flat tint
    frames: list[bytes] = []
    for hour in (3, 7, 12):
        surface = pygame.Surface((1920, 480))
        ui = scenes.new_state()
        scenes.render(surface, ui, NOW.replace(hour=hour), 50.0,
                      enabled=["planet_horizon"])
        assert ui["kind"] == "planet_horizon"
        frames.append(pygame.image.tobytes(surface.subsurface((402, 8, 1118, 472)), "RGB"))
    assert len(set(frames)) == 3


def test_planet_horizon_animates_without_rebuilding_the_composition():
    # Given: one authored noon composition
    # When: only ambient time advances
    # Then: restrained cloud drift produces a different complete frame
    surface = pygame.Surface((1920, 480))
    ui = scenes.new_state()
    scenes.render(surface, ui, NOW, 20.0, enabled=["planet_horizon"])
    assert ui["kind"] == "planet_horizon"
    first = pygame.image.tobytes(surface.subsurface((402, 8, 1118, 472)), "RGB")
    scenes.render(surface, ui, NOW, 80.0, enabled=["planet_horizon"])
    second = pygame.image.tobytes(surface.subsurface((402, 8, 1118, 472)), "RGB")
    assert second != first
