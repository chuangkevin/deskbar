"""v4 App 層：寬度/模式切換、強制同步、回今天、跳日、觸控拖曳平移的行為驗證。

_dispatch／_handle_touch_up 本身不碰 self.screen/self.logical，故不必真的顯示器：
向 dashboard.render() 要目前的 hits，drive _dispatch(x, y) 或 _handle_touch_up(x, y) 即可。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar import sync
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import dashboard
from deskbar.ui.app import App
from deskbar.ui.dashboard import TL_X0, TL_X1

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)


def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    lock = threading.Lock()
    saved = []
    app = App(state, settings, lock, on_save=lambda s: saved.append(s), alarm_store=None)
    app.view = "dashboard"
    app._saved = saved
    return app


def _dummy_surface():
    return pygame.Surface((1920, 480))


def _click(app: App, action: str) -> None:
    hits = dashboard.render(_dummy_surface(), app.state.snapshot(), app.settings, NOW,
                            anchor=app.view_anchor)
    app.hits = hits
    for h in hits:
        if h.action != action:
            continue
        cx = h.rect.x + h.rect.w / 2
        cy = h.rect.y + h.rect.h / 2
        app._dispatch(cx, cy)
        return
    raise AssertionError(f"no hit found for action={action!r}")


def test_cycle_span_dispatch_advances_and_saves(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    assert app.settings.view_span == "day"
    _click(app, "cycle_span")
    assert app.settings.view_span == "week"
    assert app._saved, "cycle_span 應呼叫 on_save"


def test_cycle_view_mode_dispatch_toggles(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    assert app.settings.view_mode == "lanes"
    _click(app, "cycle_view_mode")
    assert app.settings.view_mode == "agenda"
    _click(app, "cycle_view_mode")
    assert app.settings.view_mode == "lanes"


def test_force_sync_dispatch_sets_event(tmp_path, monkeypatch):
    sync.FORCE_SYNC.clear()
    app = _make_app(tmp_path, monkeypatch)
    _click(app, "force_sync")
    assert sync.FORCE_SYNC.is_set()
    sync.FORCE_SYNC.clear()


def test_goto_now_dispatch_clears_anchor(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.view_anchor = NOW - timedelta(days=2)
    _click(app, "goto_now")
    assert app.view_anchor is None


def test_goto_day_dispatch_sets_anchor_noon_and_day_span(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.view_span = "month"
    _click(app, "goto_day")
    assert app.view_anchor is not None
    assert app.view_anchor.hour == 12 and app.view_anchor.minute == 0
    assert app.settings.view_span == "day"


def test_drag_inside_timeline_pans_anchor_into_past(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    assert app.view_anchor is None
    t0 = datetime.now(TZ)
    app._drag_start = (700, 200)
    app._handle_touch_up(900, 200)   # dx=200，起點在時間軸區、往右拖=看過去
    assert app.view_anchor is not None
    window_len = timedelta(hours=16)     # day 檔窗口：08:00~24:00
    expected_shift = 200 / (TL_X1 - TL_X0) * window_len
    expected = t0 - expected_shift
    assert abs((app.view_anchor - expected).total_seconds()) < 3


def test_drag_starting_in_panel_area_does_not_pan(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._drag_start = (100, 200)
    app._handle_touch_up(400, 200)    # dx=300 但起點在面板區（x<=500）→ 視為點擊，不平移
    assert app.view_anchor is None


def test_small_movement_is_treated_as_click(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    hits = dashboard.render(_dummy_surface(), app.state.snapshot(), app.settings, NOW,
                            anchor=app.view_anchor)
    app.hits = hits
    gear = next(h for h in hits if h.action == "open_settings")
    cx, cy = gear.rect.x + gear.rect.w / 2, gear.rect.y + gear.rect.h / 2
    app._drag_start = (cx, cy)
    app._handle_touch_up(cx + 5, cy)   # 移動 <24px，視為點擊
    assert app.view == "settings"


def test_pan_result_clamped_to_data_window(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.view_span = "month"
    # 極端拖曳，遠超資料窗口（今天-7 ~ +30 天）
    app._drag_start = (1900, 200)
    app._handle_touch_up(501, 200)   # 幾乎滑滿整個時間軸寬度，往左拖=看未來
    assert app.view_anchor is not None
    today = datetime.now(TZ)
    hi_bound = today.date() + timedelta(days=30)
    assert app.view_anchor.date() <= hi_bound
