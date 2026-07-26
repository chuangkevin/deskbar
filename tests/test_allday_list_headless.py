"""「＋N 整日」小字點開浮層的 App 層行為：open_allday_list → 進 allday_list 檢視、
_draw_frame 疊出 detail.render_allday_list()；點外側 close 回 dashboard。"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)


def _make_app_with_many_allday(tmp_path, monkeypatch, n=30) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    events = [Event(f"e{i}", "a@x.com", "c", f"很長很長的整日事件標題{i}" * 2, midnight,
                    midnight + timedelta(days=1), True, None, None) for i in range(n)]
    state = AppState()
    state.set_events("a@x.com", events, NOW)
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None, alarm_store=None)
    app.view = "dashboard"
    app.logical = pygame.Surface((1920, 480))   # _start_transition 需要；_draw_frame 也用它
    return app


def test_open_allday_list_hit_exists_when_chips_overflow(tmp_path, monkeypatch):
    app = _make_app_with_many_allday(tmp_path, monkeypatch)
    hits = dashboard.render(app.logical, app.state.snapshot(), app.settings, NOW,
                            anchor=app.view_anchor)
    overflow = [h for h in hits if h.action == "open_allday_list"]
    assert overflow, "30 個超長整日標題應該會溢出成「＋N 整日」"
    assert len(overflow[0].data) == 30   # 浮層資料＝全部整日事件，不是只有溢出的部分


def test_clicking_overflow_chip_opens_allday_list_view(tmp_path, monkeypatch):
    app = _make_app_with_many_allday(tmp_path, monkeypatch)
    hits = dashboard.render(app.logical, app.state.snapshot(), app.settings, NOW,
                            anchor=app.view_anchor)
    app.hits = hits
    hit = next(h for h in hits if h.action == "open_allday_list")
    cx, cy = hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2
    app._dispatch(cx, cy)
    assert app.view == "allday_list"
    assert app.allday_events is not None and len(app.allday_events) == 30


def test_draw_frame_renders_allday_list_overlay_and_close_returns_to_dashboard(
        tmp_path, monkeypatch):
    app = _make_app_with_many_allday(tmp_path, monkeypatch)
    hits = dashboard.render(app.logical, app.state.snapshot(), app.settings, NOW,
                            anchor=app.view_anchor)
    app.hits = hits
    hit = next(h for h in hits if h.action == "open_allday_list")
    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)
    assert app.view == "allday_list"

    app._draw_frame(app.state.snapshot(), NOW)   # 不該炸掉，且要疊出 close/noop hits
    actions = {h.action for h in app.hits}
    assert "close" in actions
    assert "noop" in actions

    # 卡片本身是 noop（點卡片內不關閉），點卡片「外側」的空白處才會命中 close；
    # (10, 10) 在卡片 Rect(360, 40, 1200, 400) 之外，且 hits 反序命中，noop 蓋在
    # close 上方也不會誤觸。
    app._dispatch(10, 10)
    assert app.view == "dashboard"
