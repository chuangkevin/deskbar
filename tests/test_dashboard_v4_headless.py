"""v4 視圖層：寬度切換/模式切換/強制同步/回今天/月視圖/行程模式的 render() hits 驗證。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard, theme
from deskbar.viewwin import view_window

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 37, tzinfo=TZ)   # 週一


def _surf():
    return pygame.Surface((1920, 480))


def _settings_with_account():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def _state_with_event(start, end, title="會議", account="a@x.com", all_day=False):
    st = AppState()
    st.set_events(account, [Event("e1", account, "c", title, start, end, all_day, None, None)],
                 NOW)
    return st


def test_day_span_render_has_core_control_hits():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "cycle_span" in actions
    assert "cycle_view_mode" in actions
    assert "force_sync" in actions
    # 預設 day 檔且未設 anchor：不該出現回今天鈕
    assert "goto_now" not in actions


def test_syncing_state_flag_does_not_crash_and_keeps_hits():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    st.set_syncing(True)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "force_sync" in actions


def test_anchor_set_shows_goto_now():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    anchor = NOW - timedelta(days=1)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    actions = {h.action for h in hits}
    assert "goto_now" in actions


def test_week_span_without_anchor_still_shows_label_and_goto_now_hidden():
    settings = _settings_with_account()
    settings.view_span = "week"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    # span != day 時即使 anchor=None 也顯示標籤，但「回今天」只在 anchor 非 None 才出現
    assert "goto_now" not in actions


def test_month_span_returns_goto_day_hits():
    settings = _settings_with_account()
    settings.view_span = "month"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    goto_day_hits = [h for h in hits if h.action == "goto_day"]
    assert goto_day_hits, "月檔應回傳 goto_day hits"
    assert all(h.data is not None for h in goto_day_hits)


def test_agenda_mode_returns_open_detail_hits():
    # 行程模式新契約（2026-07-26）：只列「從現在起」的行程，故事件須在 NOW 之後
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    assert detail_hits


def test_agenda_mode_empty_window_still_returns_control_hits():
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = AppState()   # 沒有任何事件
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "cycle_span" in actions and "force_sync" in actions


def test_week_span_renders_long_event_without_crash():
    """規格：週＝免標籤。先確保跨小時的事件在週檔渲染不會爆炸（基本煙霧測試），
    標籤是否真的被壓下由下面的像素比對測試驗證。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    start = NOW.replace(hour=10, minute=0)
    st = _state_with_event(start, start + timedelta(hours=6), title="很長很長的會議標題文字")
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert any(h.action == "open_detail" for h in hits)


def test_week_span_shows_label_when_block_wide_enough():
    """使用者要求（2026-07-26 推翻原規格）：週檢視的事件塊只要寬度夠
    （>40px，約 4.8 小時以上）就要顯示標題（18px 小字），否則週視圖不可讀。

    驗證方式：同一個 6 小時事件（週檔寬約 51px），分別在 day／week 檔渲染，
    掃描色塊內文字帶的像素——兩檔都應該出現非底色像素（都畫了字）。
    """
    # 刻意避開 NOW（14:37）落在事件區間內：「現在」豎線會穿過色塊，
    # 混進「這格有非底色像素」的判斷，干擾標籤有無的驗證。
    start = NOW.replace(hour=18, minute=0)
    end = start + timedelta(hours=6)
    dark = theme.account_color(0)[1]      # a@x.com 預設 color=0 的色塊底色

    def _render_span(span):
        settings = _settings_with_account()
        settings.view_span = span
        st = _state_with_event(start, end, title="很長很長的會議標題文字")
        surf = _surf()
        hits = dashboard.render(surf, st.snapshot(), settings, NOW)
        block = next(h for h in hits if h.action == "open_detail")
        return surf, block.rect

    def _has_non_bg_pixel(surf, rect, bg):
        # 文字帶掃描範圍取兩種字級（day 22px 於 -14 起、week 18px 於 -12 起）的聯集，
        # 避免只挑到抗鋸齒空白列。
        y0 = int(rect.y) + int(rect.h) // 2 - 14
        x0 = int(rect.x) + 6
        for y in range(y0, y0 + 28):
            for x in range(x0, x0 + min(int(rect.w) - 10, 80)):
                if surf.get_at((x, y))[:3] != bg:
                    return True
        return False

    surf_day, r_day = _render_span("day")
    surf_week, r_week = _render_span("week")

    assert _has_non_bg_pixel(surf_day, r_day, dark), "day 檔應該畫出事件標題文字"
    assert _has_non_bg_pixel(surf_week, r_week, dark), "week 檔的寬事件塊也應該畫出標題"


def test_month_span_does_not_emit_goto_day_for_out_of_window_days():
    """規格：月視圖資料窗口是 [今天-7, 今天+30]。NOW=2026-07-27，窗口外的
    7 月 1 日（早於 7/20）不該出現 goto_day hit——避免使用者點了一個從沒同步過、
    畫面上看起來像「這天沒事」的日子，跳過去卻只是空白（假空）。"""
    settings = _settings_with_account()
    settings.view_span = "month"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    goto_day_dates = {h.data for h in hits if h.action == "goto_day"}
    assert date(2026, 7, 1) not in goto_day_dates
    assert date(2026, 7, 27) in goto_day_dates   # 今天本身一定在窗口內


def test_agenda_mode_hides_goto_now_even_with_anchor():
    """agenda 是「從現在起」的清單，跟 anchor／窗口無關——即使設了 anchor，
    agenda 模式下也不該出現「回到今天」鈕（河道模式下同樣的 anchor 會出現）。"""
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    anchor = NOW - timedelta(days=1)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    actions = {h.action for h in hits}
    assert "goto_now" not in actions

    settings.view_mode = "lanes"
    hits_lanes = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    assert "goto_now" in {h.action for h in hits_lanes}, "河道模式下同樣的 anchor 應該顯示回今天"


def test_agenda_mode_hides_window_label():
    """week 檔在河道模式下（anchor=None）一定顯示窗口標籤；agenda 模式下即使
    span=week 也不該畫——比對兩者在標籤區域的像素應該不同。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))

    settings.view_mode = "lanes"
    surf_lanes = _surf()
    dashboard.render(surf_lanes, st.snapshot(), settings, NOW)

    settings.view_mode = "agenda"
    surf_agenda = _surf()
    dashboard.render(surf_agenda, st.snapshot(), settings, NOW)

    win_start, win_end = view_window("week", NOW, TZ)
    topbar = dashboard._layout_topbar("week", NOW, win_start, win_end, False, True)
    x0, x1 = int(topbar.label_right_x - 200), int(topbar.label_right_x)
    diff = any(
        surf_lanes.get_at((x, y))[:3] != surf_agenda.get_at((x, y))[:3]
        for y in range(10, 34) for x in range(x0, x1)
    )
    assert diff, "agenda 模式不該畫窗口標籤，該區域像素應與河道模式不同"


def test_agenda_mode_on_month_span_still_uses_agenda_not_month_grid():
    settings = _settings_with_account()
    settings.view_span = "month"
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "goto_day" not in actions
    assert "open_detail" in actions
