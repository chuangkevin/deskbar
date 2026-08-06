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
        captured["cmd"] = args[2] if len(args) > 2 else (input or "")
        return subprocess.CompletedProcess(args, 0, stdout="Pairing successful", stderr="")

    monkeypatch.setattr(bt.subprocess, "run", fake_run)
    ok, msg = bt.pair("AA:BB:CC:DD:EE:01")
    assert ok and "成功" in msg
    assert "agent NoInputNoOutput" in captured["cmd"]
    assert "pair AA:BB:CC:DD:EE:01" in captured["cmd"]
    assert "trust AA:BB:CC:DD:EE:01" in captured["cmd"]


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

def test_in_work_span_normal_overnight_and_allday():
    assert brightness.in_work_span(9 * 60, 540, 1080)
    assert not brightness.in_work_span(18 * 60, 540, 1080)
    assert brightness.in_work_span(560, 540, 570), "半小時刻度窗內"
    assert not brightness.in_work_span(570, 540, 570), "終點排除"
    assert brightness.in_work_span(23 * 60, 22 * 60, 6 * 60), "跨午夜班"
    assert brightness.in_work_span(3 * 60, 22 * 60, 6 * 60)
    assert not brightness.in_work_span(12 * 60, 22 * 60, 6 * 60)
    assert brightness.in_work_span(5 * 60, 420, 420), "start==end 視為全天"


def test_effective_brightness_switches_at_off_work():
    s = Settings()
    s.work_start_min, s.work_end_min = 540, 1080
    s.brightness_day, s.brightness_night = 100, 40
    assert brightness.effective(s, 10 * 60) == 100
    assert brightness.effective(s, 20 * 60) == 40
    assert brightness.effective(s, 17 * 60 + 59) == 100, "17:59 還在上班"
    assert brightness.effective(s, 18 * 60) == 40, "18:00 整點切下班"


def test_veil_alpha_bounds():
    assert brightness.veil_alpha(100) == 0
    assert brightness.veil_alpha(40) == 153
    assert brightness.veil_alpha(10) == round(255 * 0.9)
    # 2026-07-30 深夜熄屏改制：pct<=0 ＝睡眠時段熄屏＝全黑（觸摸喚醒），
    # 一般亮度路徑仍由 effective() 保證最低 10%、不會誤觸全黑。
    assert brightness.veil_alpha(0) == 255, "熄屏＝全黑"
    assert brightness.veil_alpha(-5) == 255


# ---------------------------------------------------------------- 頁面流程

def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    saved = []
    app = App(AppState(), Settings(), threading.Lock(),
              on_save=lambda s: saved.append(1), alarm_store=None)
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda *a, **k: None
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
    _tap(app, "scr_adj", ("work_end_min", 30, 0, 1410))
    assert app.settings.work_end_min == 1110, "30 分鐘刻度"
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