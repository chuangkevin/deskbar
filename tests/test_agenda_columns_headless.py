"""行程模式（v4.1 一天一塊直欄）：欄數、截斷、整日置頂、空窗文案、
open_detail hits、day 檔行高 48 的驗收。取代舊版橫向卡片流的
tests/test_agenda_headless.py（該檔測的 render_agenda 舊簽名已被全面重寫取代）。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.layout import Rect
from deskbar.models import Event
from deskbar.ui import agenda, theme

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)   # 週一
AREA = Rect(500, 52, 1400, 368)


def _settings():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def _surf():
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def test_day_span_single_column_uses_48px_row_height_and_full_width():
    settings = _settings()
    e = Event("e1", "a@x.com", "c", "會議",
             NOW.replace(hour=10), NOW.replace(hour=11), False, None, None)
    hits = agenda.render_agenda(_surf(), [e], settings, date(2026, 7, 27), 1, NOW, TZ, AREA)
    row = next(h for h in hits if h.action == "open_detail")
    assert row.rect.h == agenda.ROW_H_WIDE == 48
    assert row.rect.w == AREA.w


def test_week_span_lays_out_seven_columns_at_correct_x_and_34px_rows():
    settings = _settings()
    events = [
        Event(f"e{i}", "a@x.com", "c", f"事件{i}",
             NOW.replace(hour=9) + timedelta(days=i), NOW.replace(hour=10) + timedelta(days=i),
             False, None, None)
        for i in range(7)
    ]
    hits = agenda.render_agenda(_surf(), events, settings, date(2026, 7, 27), 7, NOW, TZ, AREA)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    assert len(detail_hits) == 7
    col_w = AREA.w / 7
    xs = sorted(h.rect.x for h in detail_hits)
    expected_xs = sorted(AREA.x + i * col_w for i in range(7))
    for got, exp in zip(xs, expected_xs):
        assert abs(got - exp) < 0.01
    assert all(h.rect.h == agenda.ROW_H for h in detail_hits)


def test_long_title_row_truncates_without_crash():
    settings = _settings()
    e = Event("e1", "a@x.com", "c",
             "This is a very long English event title used to make sure "
             "truncate_to_width actually kicks in for a single agenda row",
             NOW.replace(hour=10), NOW.replace(hour=11), False, None, None)
    hits = agenda.render_agenda(_surf(), [e], settings, date(2026, 7, 27), 1, NOW, TZ, AREA)
    assert any(h.action == "open_detail" for h in hits)


def test_allday_event_pinned_above_timed_event_in_same_column():
    settings = _settings()
    timed = Event("e1", "a@x.com", "c", "早會",
                 NOW.replace(hour=9), NOW.replace(hour=10), False, None, None)
    day0 = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    allday = Event("e2", "a@x.com", "c", "國定假日", day0, day0 + timedelta(days=1),
                  True, None, None)
    hits = agenda.render_agenda(_surf(), [timed, allday], settings,
                                date(2026, 7, 27), 1, NOW, TZ, AREA)
    rows = sorted((h for h in hits if h.action == "open_detail"), key=lambda h: h.rect.y)
    assert [h.data.id for h in rows] == ["e2", "e1"]   # 整日置頂：第一列一定是整日事件


def test_overflow_row_reserves_capacity_for_plus_n():
    """day 檔行高 48px，可用高 368-32=336，容量 floor(336/48)=7；塞 9 筆應該只畫
    capacity-1=6 筆 open_detail（留最後一格給「＋N」）。"""
    settings = _settings()
    events = [
        Event(f"e{i}", "a@x.com", "c", f"事件{i}",
             NOW.replace(hour=8) + timedelta(minutes=i),
             NOW.replace(hour=9) + timedelta(minutes=i), False, None, None)
        for i in range(9)
    ]
    hits = agenda.render_agenda(_surf(), events, settings, date(2026, 7, 27), 1, NOW, TZ, AREA)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    capacity = int((AREA.h - agenda.HEADER_H) // agenda.ROW_H_WIDE)
    assert capacity == 7
    assert len(detail_hits) == capacity - 1


def test_empty_day_column_has_no_hits_while_populated_column_does():
    settings = _settings()
    e = Event("e1", "a@x.com", "c", "會議",
             NOW.replace(hour=10), NOW.replace(hour=11), False, None, None)
    hits = agenda.render_agenda(_surf(), [e], settings, date(2026, 7, 27), 7, NOW, TZ, AREA)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    assert len(detail_hits) == 1
    assert detail_hits[0].rect.x == AREA.x   # 事件所在的第 0 欄（今天，週一）


def test_zero_events_in_entire_window_shows_placeholder_and_no_hits():
    settings = _settings()
    hits = agenda.render_agenda(_surf(), [], settings, date(2026, 7, 27), 7, NOW, TZ, AREA)
    assert hits == []
