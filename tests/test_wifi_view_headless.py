"""Wi-Fi 設定頁：清單/鍵盤渲染契約＋app dispatch 全流程（掃描→選網→打密碼
→連線），nmcli 全程假替身、背景執行緒以輪詢等收斂。"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar import wifi as wifi_mod
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import theme, wifi_view
from deskbar.ui.app import App
from deskbar.wifi import WifiNet

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=TZ)

NETS = [
    WifiNet("Hotspot", 30, True, True, True),
    WifiNet("OfficeWifi", 82, True, False, False),
    WifiNet("OpenCafe", 64, False, False, False),
]


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _actions(hits):
    return [h.action for h in hits]


# ---------------------------------------------------------------- 渲染契約

def test_list_renders_row_hits_and_controls():
    ui = wifi_view.new_state()
    ui["nets"] = NETS
    ui["active"] = ("Hotspot", "100.98.35.59")
    hits = wifi_view.render(_surf(), ui, NOW)
    acts = _actions(hits)
    assert acts.count("wifi_pick") == 3
    assert "wifi_rescan" in acts and "wifi_back" in acts


def test_password_keyboard_covers_letters_digits_shift_and_symbols():
    ui = wifi_view.new_state()
    ui.update(phase="password", selected="OfficeWifi")
    hits = wifi_view.render(_surf(), ui, NOW)
    chars = {h.data for h in hits if h.action == "wifi_key"}
    for c in "qazm19 ":
        assert c in chars, f"鍵盤缺 {c!r}"
    ui["shift"] = True
    chars = {h.data for h in wifi_view.render(_surf(), ui, NOW)
             if h.action == "wifi_key"}
    assert "Q" in chars and "M" in chars
    ui.update(shift=False, sym=True)
    chars = {h.data for h in wifi_view.render(_surf(), ui, NOW)
             if h.action == "wifi_key"}
    for c in "!@#$%^&*()-_=+[]{};:'\",.<>?/~`":
        assert c in chars, f"符號盤缺 {c!r}"


def test_password_keyboard_has_control_keys():
    ui = wifi_view.new_state()
    ui.update(phase="password", selected="X", pw="abc")
    acts = _actions(wifi_view.render(_surf(), ui, NOW))
    for a in ("wifi_backspace", "wifi_shift", "wifi_sym", "wifi_show",
              "wifi_cancel", "wifi_connect"):
        assert a in acts, f"缺 {a}"


def test_connecting_overlay_locks_all_touches():
    ui = wifi_view.new_state()
    ui.update(phase="password", selected="X", pw="abc", busy="connect")
    assert wifi_view.render(_surf(), ui, NOW) == [], "連線中必須鎖操作"


def test_password_field_masks_by_default():
    ui = wifi_view.new_state()
    ui.update(phase="password", selected="X", pw="secret")
    masked = pygame.image.tobytes(_render_to(ui), "RGB")
    ui["show_pw"] = True
    shown = pygame.image.tobytes(_render_to(ui), "RGB")
    assert masked != shown, "遮罩與明碼畫面必須不同"


def _render_to(ui):
    s = _surf()
    wifi_view.render(s, ui, NOW)
    return s


# ---------------------------------------------------------------- app dispatch 全流程

def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    app = App(AppState(), Settings(), threading.Lock(), on_save=lambda s: None,
              alarm_store=None)
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda: None
    return app


def _wait_idle(app, timeout=3.0):
    t0 = time.monotonic()
    while app.wifi_ui["busy"] is not None:
        assert time.monotonic() - t0 < timeout, "Wi-Fi 背景執行緒未收斂"
        time.sleep(0.01)


def _tap(app, action, data=None):
    hit = next(h for h in app.hits
               if h.action == action and (data is None or h.data == data))
    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)


def _render_hits(app):
    from deskbar.ui import wifi_view as wv
    app.hits = wv.render(_surf(), app.wifi_ui, NOW)


def test_full_flow_scan_pick_type_connect(tmp_path, monkeypatch):
    connect_calls = []
    monkeypatch.setattr(wifi_mod, "scan", lambda: list(NETS))
    monkeypatch.setattr(wifi_mod, "active_info", lambda: ("Hotspot", "1.2.3.4"))
    monkeypatch.setattr(wifi_mod, "connect",
                        lambda ssid, pw=None, sec="": (connect_calls.append((ssid, pw))
                                               or (True, "activated")))
    app = _make_app(tmp_path, monkeypatch)
    app.view = "settings"
    from deskbar.ui import settings_view
    app.hits = settings_view.render(_surf(), app.state.snapshot(), app.settings, None)
    _tap(app, "open_wifi")
    assert app.view == "wifi"
    _wait_idle(app)
    assert [n.ssid for n in app.wifi_ui["nets"]] == ["Hotspot", "OfficeWifi", "OpenCafe"]

    _render_hits(app)
    _tap(app, "wifi_pick", next(n for n in NETS if n.ssid == "OfficeWifi"))
    assert app.wifi_ui["phase"] == "password"

    _render_hits(app)
    for ch in ("p", "w"):
        _tap(app, "wifi_key", ch)
    _tap(app, "wifi_shift")
    _render_hits(app)                       # shift 後鍵面變大寫，要重取 hits
    _tap(app, "wifi_key", "X")
    assert app.wifi_ui["pw"] == "pwX"
    _tap(app, "wifi_backspace")
    assert app.wifi_ui["pw"] == "pw"

    _tap(app, "wifi_connect")
    _wait_idle(app)
    assert connect_calls == [("OfficeWifi", "pw")]
    assert app.wifi_ui["phase"] == "list"
    assert app.wifi_ui["pw"] == "", "連線成功後密碼必須清空"
    assert "已連線" in app.wifi_ui["msg"]


def test_open_or_known_network_connects_without_keyboard(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(wifi_mod, "scan", lambda: list(NETS))
    monkeypatch.setattr(wifi_mod, "active_info", lambda: None)
    monkeypatch.setattr(wifi_mod, "connect",
                        lambda ssid, pw=None, sec="": (calls.append((ssid, pw)) or (True, "ok")))
    app = _make_app(tmp_path, monkeypatch)
    app.view = "wifi"
    app.wifi_ui["nets"] = list(NETS)
    _render_hits(app)
    _tap(app, "wifi_pick", next(n for n in NETS if n.ssid == "OpenCafe"))
    _wait_idle(app)
    assert calls == [("OpenCafe", None)]
    assert app.wifi_ui["phase"] == "list"


def test_connect_failure_keeps_password_phase_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(wifi_mod, "scan", lambda: list(NETS))
    monkeypatch.setattr(wifi_mod, "active_info", lambda: None)
    monkeypatch.setattr(wifi_mod, "connect", lambda ssid, pw=None, sec="": (False, "bad key"))
    app = _make_app(tmp_path, monkeypatch)
    app.view = "wifi"
    app.wifi_ui.update(phase="password", selected="OfficeWifi", pw="wrong")
    _render_hits(app)
    _tap(app, "wifi_connect")
    _wait_idle(app)
    assert app.wifi_ui["phase"] == "password", "失敗要留在鍵盤讓人改密碼重試"
    assert "連線失敗" in app.wifi_ui["msg"]
    assert app.wifi_ui["pw"] == "wrong", "失敗不清使用者打的字"


def test_wifi_view_rerenders_every_iteration(tmp_path, monkeypatch):
    """Wi-Fi 頁走 5fps 輪詢重繪（背景執行緒改 wifi_ui 沒有 seq 可觸發）。"""
    pygame.init()
    monkeypatch.setattr(wifi_mod, "scan", lambda: [])
    monkeypatch.setattr(wifi_mod, "active_info", lambda: None)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW

    monkeypatch.setattr("datetime.datetime", _Frozen)
    app = _make_app(tmp_path, monkeypatch)
    app.view = "wifi"
    app._last_seq = app.state.snapshot().seq
    app._last_minute = NOW.minute
    flips = []
    app._flip = lambda: flips.append(1)
    clock = pygame.time.Clock()
    app._run_iteration(clock, True)
    app._run_iteration(clock, True)
    assert len(flips) == 2
