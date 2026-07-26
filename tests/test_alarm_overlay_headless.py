import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.alarms import Alarm
from deskbar.ui import alarm_overlay


def test_overlay_returns_fullscreen_dismiss():
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    surf = pygame.Surface((1920, 480))
    a = Alarm(id="x1", time="09:00", days=[], label="打卡", enabled=True)
    now = datetime(2026, 7, 27, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    hits = alarm_overlay.render(surf, a, now)
    assert len(hits) == 1 and hits[0].action == "dismiss_alarm"
    assert hits[0].rect.contains(0, 0) and hits[0].rect.contains(1919, 479)
    pygame.quit()
