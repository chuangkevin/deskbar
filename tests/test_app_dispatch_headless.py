"""覆蓋 App._dispatch 對鬧鐘的實際行為（新增/切換/刪除），不需要真的顯示器。

_dispatch 本身不碰 self.screen/self.logical，故不必呼叫 App.run()／_init_display()；
hit rect 直接向 alarm_view.render() 要，drive _dispatch(x, y) 即可。
"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from deskbar.alarms import AlarmStore
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import alarm_view
from deskbar.ui.app import App

NOW = datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    state = AppState()
    settings = Settings()
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None, alarm_store=store)
    app.view = "alarms"
    return app


def _click(app: App, action: str, data_filter=None) -> None:
    """render alarm_view 拿最新 hits，找到指定 action 的 hit，往其中心點 dispatch。"""
    hits = alarm_view.render(_dummy_surface(), app.alarm_store, app.alarm_draft, NOW)
    app.hits = hits
    for h in hits:
        if h.action != action:
            continue
        if data_filter is not None and h.data != data_filter:
            continue
        cx = h.rect.x + h.rect.w / 2
        cy = h.rect.y + h.rect.h / 2
        app._dispatch(cx, cy)
        return
    raise AssertionError(f"no hit found for action={action!r} data_filter={data_filter!r}")


def _dummy_surface():
    import pygame
    return pygame.Surface((1920, 480))


def test_add_alarm_dispatch(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.alarm_draft["hour"] = 7
    app.alarm_draft["minute"] = 5
    app.alarm_draft["days"] = {3, 1, 5}

    _click(app, "save_alarm")

    alarms = app.alarm_store.list()
    assert len(alarms) == 1
    a = alarms[0]
    assert a.time == "07:05"
    assert a.days == [1, 3, 5]
    assert app.alarm_draft["days"] == set()


def test_add_arrival_alarm_and_toggle_existing_dispatch(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    _click(app, "draft_arrival_trigger")
    _click(app, "save_alarm")
    added = app.alarm_store.list()[0]
    assert added.arrival_trigger is True
    assert app.alarm_draft["arrival_trigger"] is False

    _click(app, "toggle_alarm_arrival", data_filter=added.id)
    assert app.alarm_store.list()[0].arrival_trigger is False


def test_edit_alarm_dispatch(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    added = app.alarm_store.add("09:00", [0], "公司打卡")
    _click(app, "edit_alarm", data_filter=added.id)
    assert app.alarm_draft["editing_id"] == added.id
    assert app.alarm_draft["label_override"] == "公司打卡"

    app.alarm_draft["hour"] = 8
    app.alarm_draft["minute"] = 45
    app.alarm_draft["arrival_trigger"] = True
    _click(app, "save_alarm")
    got = app.alarm_store.list()[0]
    assert (got.time, got.label, got.arrival_trigger) == ("08:45", "公司打卡", True)


def test_toggle_alarm_dispatch(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    added = app.alarm_store.add("09:00", [0], "打卡")
    assert added.enabled is True

    _click(app, "toggle_alarm", data_filter=added.id)

    got = {a.id: a for a in app.alarm_store.list()}
    assert got[added.id].enabled is False

    _click(app, "toggle_alarm", data_filter=added.id)
    got = {a.id: a for a in app.alarm_store.list()}
    assert got[added.id].enabled is True


def test_delete_alarm_dispatch(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    added = app.alarm_store.add("09:00", [], "吃藥")
    assert len(app.alarm_store.list()) == 1

    _click(app, "delete_alarm", data_filter=added.id)

    assert app.alarm_store.list() == []
