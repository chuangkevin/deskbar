"""行程模式（agenda）卡片：標題量測式兩行換行、超量收成「＋N」膠囊。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.layout import Rect
from deskbar.models import Event
from deskbar.ui import agenda, theme

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)
AREA = Rect(500, 52, 1400, 368)


def _settings():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def test_long_title_wraps_without_crash_and_stays_within_two_lines():
    settings = _settings()
    e = Event("e1", "a@x.com", "c", "This is a very long English event title used to test wrap",
              NOW + timedelta(hours=1), NOW + timedelta(hours=2), False, None, None)
    surf = pygame.Surface((1920, 480))
    hits = agenda.render_agenda(surf, [e], settings, NOW, NOW + timedelta(days=1), NOW, AREA)
    assert any(h.action == "open_detail" for h in hits)


def test_extra_count_pill_drawn_with_card_fill_and_border():
    """超過 MAX_CARDS 的「＋N」要有 card 底＋panel_line 邊框的膠囊外觀，
    跟「＋N 整日」一致——量測膠囊區域內同時出現 card 色與 panel_line 色像素。"""
    settings = _settings()
    events = [
        Event(f"e{i}", "a@x.com", "c", f"事件{i}",
             NOW + timedelta(hours=i + 1), NOW + timedelta(hours=i + 2), False, None, None)
        for i in range(agenda.MAX_CARDS + 2)
    ]
    surf = pygame.Surface((1920, 480))
    surf.fill((15, 15, 15))
    hits = agenda.render_agenda(surf, events, settings, NOW, NOW + timedelta(days=1), NOW, AREA)
    assert len([h for h in hits if h.action == "open_detail"]) == agenda.MAX_CARDS

    x = AREA.x + agenda.MAX_CARDS * agenda.CARD_W
    x_end = min(x + agenda.CARD_W, surf.get_width())
    seen = {surf.get_at((px, py))[:3]
           for py in range(int(AREA.y), int(AREA.y) + int(AREA.h))
           for px in range(int(x), int(x_end))}
    assert theme.C["card"] in seen
    assert theme.C["panel_line"] in seen


def test_no_upcoming_events_shows_placeholder_text():
    settings = _settings()
    surf = pygame.Surface((1920, 480))
    hits = agenda.render_agenda(surf, [], settings, NOW, NOW + timedelta(days=1), NOW, AREA)
    assert hits == []
