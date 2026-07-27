"""藍牙配對（deskbar.bt＋bt_view）與螢幕頁（screen_view＋brightness）：
解析純函式、配對指令組裝、配對成功自動設感應目標、解除配對清目標、
亮度排程數學、上下班調整流程與持久化。"""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar import brightness, bt
from deskbar.bt import BtDevice
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import bt_view, screen_view, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 22, 0, tzinfo=TZ)


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


# ---------------------------------------------------------------- bt 解析

def test_parse_devices_filters_and_marks_paired():
    text = "\n".join([
        "Device C4:C1:7D:63:07:88 Kevin 的 iPhone",
        "Device AA:BB:CC:DD:EE:01 POCO F5 Pro",
        "Device AA:BB:CC:DD:EE:02 AA-BB-CC-DD-EE-02",   # 名稱=MAC → 視為無名
        "垃圾行 not a device",
        "Device BROKEN",
    ])
    devs = bt.parse_devices(text, paired_macs={"AA:BB:CC:DD:EE:01"})
    assert [d.mac for d in devs][0] == "AA:BB:CC:DD:EE:01", "已配對排最前"
    poco = devs[0]
    assert poco.paired and poco.name == "POCO F5 Pro"
    unnamed = next(d for d in devs if d.mac == "AA:BB:CC:DD:EE:02")
    assert unnamed.name == ""
    assert len(devs) == 3


def test_pair_uses_noinput_agent_and_detects_success(monkeypatch):
    captured = {}

    def fake_run(args, capture_output, text, timeout, input=None):
        captured["input"] = input
        return subprocess.CompletedProcess(args, 0, stdout="Pairing successful", stderr="")

    monkeypatch.setattr(bt.subprocess, "run", fake_run)
    ok, msg = bt.pair("AA:BB:CC:DD:EE:01")
    assert ok and "成功" in msg
    assert "agent NoInputNoOutput" in captured["input"]
    assert "pair AA:BB:CC:DD:EE:01" in captured["input"]
    assert "trust AA:BB:CC:DD:EE:01" in captured["input"]


def test_pair_already_paired_counts_as_success(monkeypatch):
    monkeypatch.setattr(bt.subprocess, "run",
                        lambda args, capture_output, text, timeout, input=None:
                        subprocess.CompletedProcess(args, 1,
                                                    stdout="org.bluez.Error.AlreadyExists",
                                                    stderr=""))
    ok, _ = bt.pair("AA:BB:CC:DD:EE:01")
    assert ok


def test_bt_failures_never_raise(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("bluetoothctl")

    monkeypatch.setattr(bt.subprocess, "run", boom)
    assert bt.scan() == []
    assert bt.paired_macs() == set()
    ok, _ = bt.pair("X")
    assert ok is False


# ---------------------------------------------------------------- brightness

def test_in_work_hours_normal_overnight_and_allday():
    assert brightness.in_work_hours(9, 9, 18)
    assert not brightness.in_work_hours(18, 9, 18)
    assert brightness.in_work_hours(23, 22, 6), "跨午夜班"
    assert brightness.in_work_hours(3, 22, 6)
    assert not brightness.in_work_hours(12, 22, 6)
    assert brightness.in_work_hours(5, 7, 7), "start==end 視為全天"


def test_effective_brightness_switches_at_off_work():
    s = Settings()
    s.work_start_hour, s.work_end_hour = 9, 18
    s.brightness_day, s.brightness_night = 100, 40
    assert brightness.effective(s, 10) == 100
    assert brightness.effective(s, 20) == 40


def test_veil_alpha_bounds():
    assert brightness.veil_alpha(100) == 0
    assert brightness.veil_alpha(40) == 153
    assert brightness.veil_alpha(10) == round(255 * 0.9)
    assert brightness.veil_alpha(-5) == round(255 * 0.9), "下限夾住，永不全黑"


# ---------------------------------------------------------------- 頁面流程

def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    saved = []
    app = App(AppState(), Settings(), threading.Lock(),
              on_save=lambda s: saved.append(1), alarm_store=None)
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda: None
    app._saved = saved
    return app


def _tap(app, action, data=None):
    hit = next(h for h in app.hits
               if h.action == action and (data is None or h.data == data))
    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)


def test_screen_page_adjusts_hours_and_brightness_with_persistence(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.view = "screen"
    app.hits = screen_view.render(_surf(), app.settings)
    _tap(app, "scr_adj", ("work_end_hour", 1, 0, 23))
    assert app.settings.work_end_hour == 19
    _tap(app, "scr_adj", ("brightness_night", -10, 10, 100))
    assert app.settings.brightness_night == 30
    # 夾住下限：連按不會低於 10
    for _ in range(5):
        _tap(app, "scr_adj", ("brightness_night", -10, 10, 100))
    assert app.settings.brightness_night == 10
    assert app._saved, "調整需持久化"
    acts = [h.action for h in screen_view.render(_surf(), app.settings)]
    assert "rotate" in acts and "open_settings" in acts


def test_bt_page_pair_sets_presence_target(tmp_path, monkeypatch):
    dev = BtDevice("AA:BB:CC:DD:EE:01", "POCO F5 Pro", paired=False)
    monkeypatch.setattr(bt, "pair", lambda mac: (True, "配對成功"))
    monkeypatch.setattr(bt, "scan", lambda seconds=8: [
        BtDevice("AA:BB:CC:DD:EE:01", "POCO F5 Pro", paired=True)])
    app = _make_app(tmp_path, monkeypatch)
    app.view = "bt"
    app.bt_ui["devices"] = [dev]
    app.hits = bt_view.render(_surf(), app.bt_ui, app.settings, NOW)
    _tap(app, "bt_pick", dev)
    t0 = time.monotonic()
    while app.bt_ui["busy"] is not None:
        assert time.monotonic() - t0 < 3
        time.sleep(0.01)
    assert app.settings.presence_mac == "AA:BB:CC:DD:EE:01", "配對成功即設為感應目標"
    assert app._saved


def test_bt_page_unpair_clears_presence_target(tmp_path, monkeypatch):
    dev = BtDevice("AA:BB:CC:DD:EE:01", "POCO F5 Pro", paired=True)
    monkeypatch.setattr(bt, "unpair", lambda mac: (True, "已解除配對"))
    monkeypatch.setattr(bt, "scan", lambda seconds=8: [])
    app = _make_app(tmp_path, monkeypatch)
    app.view = "bt"
    app.settings.presence_mac = dev.mac
    app.bt_ui["devices"] = [dev]
    app.hits = bt_view.render(_surf(), app.bt_ui, app.settings, NOW)
    _tap(app, "bt_unpair", dev.mac)
    t0 = time.monotonic()
    while app.bt_ui["busy"] is not None:
        assert time.monotonic() - t0 < 3
        time.sleep(0.01)
    assert app.settings.presence_mac == "", "解除配對的裝置不能繼續當感應目標"


def test_bt_pairing_overlay_locks_touches():
    ui = bt_view.new_state()
    ui.update(busy="pair", devices=[BtDevice("AA:BB:CC:DD:EE:01", "X", False)])
    assert bt_view.render(_surf(), ui, Settings(), NOW) == []