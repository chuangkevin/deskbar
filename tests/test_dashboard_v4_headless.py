"""v4 視圖層：寬度切換/模式切換/強制同步/回今天/月視圖/行程模式的 render() hits 驗證。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard

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
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
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


def test_agenda_mode_on_month_span_still_uses_agenda_not_month_grid():
    settings = _settings_with_account()
    settings.view_span = "month"
    settings.view_mode = "agenda"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "goto_day" not in actions
    assert "open_detail" in actions
