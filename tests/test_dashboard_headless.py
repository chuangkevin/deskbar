import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard

TZ = ZoneInfo("Asia/Taipei")


def test_render_returns_hits_without_crash():
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    surf = pygame.Surface((1920, 480))
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    now = datetime(2026, 7, 27, 14, 37, tzinfo=TZ)
    st = AppState()
    st.set_events("a@x.com", [Event("e", "a@x.com", "c", "週會",
                                    now.replace(hour=10), now.replace(hour=11),
                                    False, None, None)], now)
    hits = dashboard.render(surf, st.snapshot(), settings, now)
    actions = {h.action for h in hits}
    assert "open_settings" in actions and "open_detail" in actions
    pygame.quit()
