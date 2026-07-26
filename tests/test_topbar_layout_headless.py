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
    """對 span×goto_now×label 全排列，逐一驗證：回到今天鈕緊貼寬度鈕左側且不重疊；
    標籤右緣與其左方元素之間、chips 右界與其左方元素之間都保有 >= TOPBAR_GAP。"""
    for span in ["half", "day", "week", "month"]:
        win_start, win_end = view_window(span, NOW, TZ)
        for show_goto_now in (False, True):
            for show_label in (False, True):
                topbar = dashboard._layout_topbar(span, NOW, win_start, win_end,
                                                  show_goto_now, show_label)
                right_boundary = dashboard.SPAN_BTN.x
                if topbar.goto_now_rect is not None:
                    gn = topbar.goto_now_rect
                    # 緊貼寬度鈕左側：右緣剛好等於寬度鈕左緣，中間不留縫也不重疊。
                    assert gn.x + gn.w == dashboard.SPAN_BTN.x
                    assert gn.w == dashboard.GOTO_NOW_W
                    right_boundary = gn.x
                if topbar.label_text:
                    label_w = theme.font(22).size(topbar.label_text)[0]
                    assert topbar.label_right_x <= right_boundary - dashboard.TOPBAR_GAP
                    right_boundary = topbar.label_right_x - label_w
                assert topbar.chip_right_x <= right_boundary - dashboard.TOPBAR_GAP
                assert topbar.chip_right_x < dashboard.SPAN_BTN.x


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


def _chip_row_hits(hits):
    return [h for h in hits if h.rect.y == dashboard.CHIP_ROW_Y]


def test_allday_chips_overflow_instead_of_overlapping_topbar():
    """30 個超長標題的整日事件（遠超真實資料量 14 筆）：多出來的一律收進
    「＋N 整日」小字，任何 chip／溢出小字都不能畫進寬度鈕或視窗標籤的地盤。"""
    settings, events = _allday_settings_and_events(30, long_title=True)
    st = AppState()
    st.set_events("a@x.com", events, NOW)
    settings.view_span = "week"     # 週檔一定顯示窗口標籤；沒有 anchor 故不顯示回到今天
    win_start, win_end = view_window("week", NOW, TZ)
    topbar = dashboard._layout_topbar("week", NOW, win_start, win_end, False, True)

    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    chip_hits = _chip_row_hits(hits)
    assert any(h.action == "open_allday_list" for h in hits), "30 個超長標題必定溢出"

    for h in chip_hits:
        assert h.rect.x + h.rect.w <= topbar.chip_right_x + 1e-6
        assert h.rect.x + h.rect.w <= dashboard.SPAN_BTN.x

    ordered = sorted(chip_hits, key=lambda h: h.rect.x)
    for prev, cur in zip(ordered, ordered[1:]):
        assert prev.rect.x + prev.rect.w <= cur.rect.x, "整日 chips 之間不可重疊"


def test_allday_chips_with_anchor_and_realistic_count_stay_clear_of_goto_now():
    """比照真實資料量級（14 筆整日）＋設了 anchor（回到今天鈕、視窗標籤都出現）：
    最擁擠的排列組合，chips 仍不可越界進回到今天鈕／寬度鈕／模式鈕。"""
    anchor = NOW - timedelta(days=2)
    settings, events = _allday_settings_and_events(14, long_title=False, day=anchor)
    st = AppState()
    st.set_events("a@x.com", events, NOW)
    settings.view_span = "day"
    win_start, win_end = view_window("day", anchor, TZ)
    topbar = dashboard._layout_topbar("day", anchor, win_start, win_end, True, True)
    assert topbar.goto_now_rect is not None

    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    chip_hits = _chip_row_hits(hits)
    assert chip_hits, "14 筆整日事件在 1920px 寬下應該至少畫得出幾個 chip"

    for h in chip_hits:
        assert h.rect.x + h.rect.w <= topbar.chip_right_x + 1e-6
        assert h.rect.x + h.rect.w <= topbar.goto_now_rect.x
        assert h.rect.x + h.rect.w <= dashboard.SPAN_BTN.x
        assert h.rect.x + h.rect.w <= dashboard.MODE_BTN.x

    ordered = sorted(chip_hits, key=lambda h: h.rect.x)
    for prev, cur in zip(ordered, ordered[1:]):
        assert prev.rect.x + prev.rect.w <= cur.rect.x


def test_zero_allday_events_renders_without_overflow_chip():
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    st = AppState()
    st.set_events("a@x.com", [], NOW)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert "open_allday_list" not in {h.action for h in hits}
