"""週檔河道（v4.1 帳號×日格子）：7 欄、goto_day hits 帶正確 date、溢出＋N、
跨帳號列的驗收。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.layout import Rect
from deskbar.models import Event
from deskbar.ui import theme, weekgrid

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)   # 週一
WEEK_START = date(2026, 7, 27)
AREA = Rect(500, 52, 1400, 368)


def _settings(*emails):
    s = Settings()
    for e in emails:
        s.ensure_account(e).calendars["c"] = True
    return s


def _surf():
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def test_seven_columns_produce_seven_goto_day_hits_with_correct_dates():
    settings = _settings("a@x.com")
    hits = weekgrid.render_week(_surf(), [], ["a@x.com"], settings, WEEK_START, NOW, TZ, AREA)
    goto_hits = [h for h in hits if h.action == "goto_day"]
    assert len(goto_hits) == 7
    assert sorted(h.data for h in goto_hits) == [WEEK_START + timedelta(days=i)
                                                 for i in range(7)]


def test_goto_day_hit_covers_whole_cell_even_when_empty():
    """即使某天完全沒有行程，那一格照樣要有 goto_day hit（跟月視圖窗口內同規則）。"""
    settings = _settings("a@x.com")
    hits = weekgrid.render_week(_surf(), [], ["a@x.com"], settings, WEEK_START, NOW, TZ, AREA)
    assert len(hits) == 7
    assert all(h.action == "goto_day" for h in hits)


def test_cross_account_rows_each_have_own_seven_cells():
    settings = _settings("a@x.com", "b@y.com")
    e_a = Event("ea", "a@x.com", "c", "A的會議", NOW.replace(hour=9), NOW.replace(hour=10),
               False, None, None)
    e_b = Event("eb", "b@y.com", "c", "B的會議", NOW.replace(hour=9), NOW.replace(hour=10),
               False, None, None)
    hits = weekgrid.render_week(_surf(), [e_a, e_b], ["a@x.com", "b@y.com"], settings,
                                WEEK_START, NOW, TZ, AREA)
    goto_hits = [h for h in hits if h.action == "goto_day"]
    assert len(goto_hits) == 14   # 2 帳號 × 7 天

    row_h = (AREA.h - weekgrid.HEADER_H) / 2
    row0_y = AREA.y + weekgrid.HEADER_H
    row1_y = row0_y + row_h
    today_row0 = next(h for h in goto_hits
                      if h.data == WEEK_START and abs(h.rect.y - row0_y) < 0.01)
    today_row1 = next(h for h in goto_hits
                      if h.data == WEEK_START and abs(h.rect.y - row1_y) < 0.01)
    assert abs(today_row0.rect.h - row_h) < 0.01
    assert abs(today_row1.rect.h - row_h) < 0.01


def test_events_stay_in_their_own_account_row_not_the_other():
    """跨帳號：A 的行程只該讓 A 那一列那一格畫出微列文字，B 那一列同一天要
    保持空白（沒有微列內容）——用像素量測驗證，而不是只看 hit 數量。"""
    settings = _settings("a@x.com", "b@y.com")
    e_a = Event("ea", "a@x.com", "c", "A的會議", NOW.replace(hour=9), NOW.replace(hour=10),
               False, None, None)
    surf = _surf()
    hits = weekgrid.render_week(surf, [e_a], ["a@x.com", "b@y.com"], settings,
                                WEEK_START, NOW, TZ, AREA)
    goto_hits = [h for h in hits if h.action == "goto_day"]
    row_h = (AREA.h - weekgrid.HEADER_H) / 2
    row1_y = AREA.y + weekgrid.HEADER_H + row_h
    b_today_cell = next(h for h in goto_hits
                        if h.data == WEEK_START and abs(h.rect.y - row1_y) < 0.01)
    x0, x1 = int(b_today_cell.rect.x) + 4, int(b_today_cell.rect.x + b_today_cell.rect.w) - 4
    y0, y1 = int(b_today_cell.rect.y) + 4, int(b_today_cell.rect.y + b_today_cell.rect.h) - 4
    all_bg = all(
        surf.get_at((x, y))[:3] == theme.C["bg"]
        for y in range(y0, y1) for x in range(x0, x1))
    assert all_bg, "B 帳號的今天格子不該出現 A 的行程微列"


def test_overflow_shows_plus_n_when_cell_exceeds_capacity_without_crash():
    settings = _settings("a@x.com")
    events = [
        Event(f"e{i}", "a@x.com", "c", f"事件{i}",
             NOW.replace(hour=8) + timedelta(minutes=i),
             NOW.replace(hour=8, minute=30) + timedelta(minutes=i), False, None, None)
        for i in range(30)
    ]
    surf = _surf()
    hits = weekgrid.render_week(surf, events, ["a@x.com"], settings, WEEK_START, NOW, TZ, AREA)
    goto_hits = [h for h in hits if h.action == "goto_day"]
    assert len(goto_hits) == 7   # goto_day 是整格，不隨事件數量改變

    row_h = AREA.h - weekgrid.HEADER_H     # 單一帳號：整個 body 高度都是它的列
    capacity = max(1, int(row_h // weekgrid.MICRO_ROW_H))
    assert capacity < 30, "測試前提：容量必須小於事件數才有溢出可驗"

    cell = next(h for h in goto_hits if h.data == WEEK_START)
    last_row_y = int(cell.rect.y) + (capacity - 1) * weekgrid.MICRO_ROW_H
    region_has_ink = any(
        surf.get_at((x, y))[:3] != theme.C["bg"]
        for y in range(last_row_y, last_row_y + weekgrid.MICRO_ROW_H)
        for x in range(int(cell.rect.x) + 2, int(cell.rect.x) + int(cell.rect.w) - 2))
    assert region_has_ink, "容量耗盡的最後一格微列應該畫出「＋N」文字"
