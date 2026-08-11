"""頂欄佈局管理（_layout_topbar／整日 chips 溢出）的硬性驗收條件：
任何資料量、任何標籤長度下，頂帶（y=0..50）固定元素互不重疊。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard, theme
from deskbar.viewwin import view_window

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 37, tzinfo=TZ)


def _surf():
    return pygame.Surface((1920, 480))


def test_layout_topbar_maintains_min_gap_for_every_combo():
    """對 span×goto_now×label 全排列，逐一驗證：回到今天鈕緊貼「中欄切換鈕」
    左側且不重疊（2026-07-30 起 CENTER_BTN 固定佔原本回到今天的位置——首日
    重疊實機翻車）；標籤右緣與其左方元素之間、chips 右界與其左方元素之間
    都保有 >= TOPBAR_GAP。"""
    for span in ["half", "day", "week", "month"]:
        win_start, win_end = view_window(span, NOW, TZ)
        for show_goto_now in (False, True):
            for show_label in (False, True):
                topbar = dashboard._layout_topbar(span, NOW, win_start, win_end,
                                                  show_goto_now, show_label)
                right_boundary = dashboard.WORK_BTN.x
                if topbar.goto_now_rect is not None:
                    gn = topbar.goto_now_rect
                    # 緊貼工作 Sessions 切換鈕左側：右緣剛好等於其左緣，不留縫也不重疊。
                    assert gn.x + gn.w == dashboard.WORK_BTN.x
                    assert gn.w == dashboard.GOTO_NOW_W
                    right_boundary = gn.x
                if topbar.label_text:
                    label_w = theme.font(22).size(topbar.label_text)[0]
                    assert topbar.label_right_x <= right_boundary - dashboard.TOPBAR_GAP
                    right_boundary = topbar.label_right_x - label_w
                assert topbar.chip_right_x <= right_boundary - dashboard.TOPBAR_GAP
                assert topbar.chip_right_x < dashboard.WORK_BTN.x


def _allday_settings_and_events(n: int, long_title: bool,
                                day: datetime = NOW) -> tuple[Settings, list[Event]]:
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    events = []
    for i in range(n):
        title = ("超級霹靂無敵冗長會議標題卡到爆炸" * 3) if long_title else f"事件{i}"
        events.append(Event(f"e{i}", "a@x.com", "c", title, midnight,
                            midnight + timedelta(days=1), True, None, None))
    return settings, events


def test_zero_allday_events_renders_without_overflow_chip():
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    st = AppState()
    st.set_events("a@x.com", [], NOW)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert "open_allday_list" not in {h.action for h in hits}


def test_allday_events_never_produce_topbar_chip_hits():
    """2026-07-27：頂欄整日行程膠囊（_render_allday／_layout_allday_chips）已整段
    移除——即使塞進大量長標題整日事件，也不該再有 open_allday_list hit；頂帶
    （y<52，寬度/模式鈕與回到今天鈕所在的那條）也不該再出現任何 chip 產生的
    open_detail hit，該區域只允許既有的三個控制鈕。整日事件改在 agenda 模式的
    日欄與 weekgrid 的格子內顯示，不再佔用頂帶空間。"""
    settings, events = _allday_settings_and_events(30, long_title=True)
    st = AppState()
    st.set_events("a@x.com", events, NOW)
    settings.view_span = "week"
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert "open_allday_list" not in {h.action for h in hits}
    # 中欄頂帶（x>=TL_X0、y<52）：整日 chips 移除前會擠在這塊，現在只允許既有的
    # 寬度/模式/回到今天三顆控制鈕。
    topbar_zone_hits = [h for h in hits if h.rect.x >= dashboard.TL_X0 and h.rect.y < 52]
    assert topbar_zone_hits and all(
        h.action in ("cycle_span", "cycle_view_mode", "goto_now", "toggle_center", "open_work_sessions")
        for h in topbar_zone_hits), \
        f"頂欄（x>=TL_X0, y<52）不該再有整日 chip 產生的 hit：{topbar_zone_hits}"
