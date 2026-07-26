"""整合驗收（task-40）：把 weatherfx／presence／transitions 三條並行線接進
dashboard.py／app.py／settings_view.py 的實際掛載點是否生效。

個別模組自身的行為細節已由各自的測試檔覆蓋（test_weatherfx_headless.py／
test_presence.py／test_transitions_headless.py），這裡只驗證「掛載本身有沒有接對」：
presence 過濾＋鎖頭圖示、settings_view 開關鈕、app.py toggle_presence dispatch、
切換過場 SlideTransition 生命週期、weather_tick 每秒遞增一次、開機 splash 可跳過。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.presence import PresenceState
from deskbar.store import AppState
from deskbar.ui import dashboard, settings_view, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)


def _surf():
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def _settings_two_accounts() -> Settings:
    settings = Settings()
    settings.ensure_account("hidden@x.com").calendars["c"] = True
    settings.ensure_account("open@x.com").calendars["c"] = True
    return settings


def _state_with_events() -> AppState:
    st = AppState()
    st.set_events("hidden@x.com", [Event("h1", "hidden@x.com", "c", "私人門診",
                  NOW.replace(hour=15), NOW.replace(hour=16), False, None, None)], NOW)
    st.set_events("open@x.com", [Event("o1", "open@x.com", "c", "工作會議",
                  NOW.replace(hour=15), NOW.replace(hour=16), False, None, None)], NOW)
    return st


def _accounts_with_open_detail(hits) -> set:
    return {h.data.account for h in hits if h.action == "open_detail" and hasattr(h.data, "account")}


# ---------------------------------------------------------------- presence 過濾


def test_presence_hides_only_configured_account_when_absent():
    settings = _settings_two_accounts()
    settings.presence_enabled = True
    settings.presence_hide_accounts = ["hidden@x.com"]
    st = _state_with_events()
    st.set_presence(PresenceState(present=False, rssi=None, last_seen=None, enabled=True))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    accounts = _accounts_with_open_detail(hits)
    assert "hidden@x.com" not in accounts
    assert "open@x.com" in accounts


def test_presence_shows_everything_when_phone_present():
    settings = _settings_two_accounts()
    settings.presence_enabled = True
    settings.presence_hide_accounts = ["hidden@x.com"]
    st = _state_with_events()
    st.set_presence(PresenceState(present=True, rssi=None, last_seen=NOW, enabled=True))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert "hidden@x.com" in _accounts_with_open_detail(hits)


def test_presence_disabled_never_filters_even_when_absent():
    """presence_enabled=False（預設）：即使已經設定了隱藏名單且 snap.presence.present
    是 False，也完全不觸發過濾——功能沒開就是零行為差異，不會有人手滑設了隱藏名單就
    整排行程消失。"""
    settings = _settings_two_accounts()
    settings.presence_hide_accounts = ["hidden@x.com"]   # 只設隱藏名單、沒開開關
    st = _state_with_events()
    st.set_presence(PresenceState(present=False, rssi=None, last_seen=None, enabled=False))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    assert "hidden@x.com" in _accounts_with_open_detail(hits)


# ---------------------------------------------------------------- 右上角鎖頭圖示


def test_presence_lock_icon_warn_color_when_hiding():
    settings = _settings_two_accounts()
    settings.presence_enabled = True
    settings.presence_hide_accounts = ["hidden@x.com"]
    st = _state_with_events()
    st.set_presence(PresenceState(present=False, rssi=None, last_seen=None, enabled=True))
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    assert surf.get_at((1878, 30))[:3] == theme.C["warn"]


def test_presence_lock_icon_muted_color_when_enabled_but_present():
    settings = _settings_two_accounts()
    settings.presence_enabled = True
    settings.presence_hide_accounts = ["hidden@x.com"]
    st = _state_with_events()
    st.set_presence(PresenceState(present=True, rssi=None, last_seen=NOW, enabled=True))
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    assert surf.get_at((1878, 30))[:3] == theme.C["muted"]


def test_presence_lock_icon_absent_when_feature_disabled():
    settings = _settings_two_accounts()   # presence_enabled 預設 False
    st = _state_with_events()
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    assert surf.get_at((1878, 30))[:3] == theme.C["bg"]


# ---------------------------------------------------------------- settings_view 開關鈕


def test_settings_view_has_presence_toggle_button():
    settings = Settings()
    hits = settings_view.render(_surf(), AppState().snapshot(), settings, None)
    toggle = next((h for h in hits if h.action == "toggle_presence"), None)
    assert toggle is not None
    assert toggle.rect.h >= 48, "觸控目標高度規範 >= 48px"


# ---------------------------------------------------------------- app.py dispatch


def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    lock = threading.Lock()
    saved = []
    app = App(state, settings, lock, on_save=lambda s: saved.append(s), alarm_store=None)
    app.view = "settings"
    app._saved = saved
    return app


def test_toggle_presence_dispatch_flips_setting_and_saves(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    hits = settings_view.render(_surf(), app.state.snapshot(), app.settings, None)
    app.hits = hits
    hit = next(h for h in hits if h.action == "toggle_presence")
    assert app.settings.presence_enabled is False
    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)
    assert app.settings.presence_enabled is True
    assert app._saved, "toggle_presence 應呼叫 on_save"
    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)
    assert app.settings.presence_enabled is False, "再點一次應該切回關"


# ---------------------------------------------------------------- 切換過場 SlideTransition


def _make_dashboard_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None, alarm_store=None)
    app.view = "dashboard"
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda: None    # 略過真正顯示器 flip，只驗證過場狀態機本身
    return app


def test_transition_lifecycle_starts_and_ends_via_slide_transition(tmp_path, monkeypatch):
    app = _make_dashboard_app(tmp_path, monkeypatch)
    assert app._transition.active() is False
    assert app._transition_start is None

    app._start_transition()
    assert app._transition.active() is True
    assert app._transition_start is not None

    app._render_transition_frame(NOW)     # 剛啟動，elapsed 極短，過場應仍在進行中
    assert app._transition.active() is True
    assert app._transition_start is not None

    app._transition_start = time.monotonic() - 1.0   # 模擬已經過了遠超過 DURATION(0.2s)
    app._render_transition_frame(NOW)
    assert app._transition.active() is False
    assert app._transition_start is None


def test_start_transition_noop_without_logical_surface(tmp_path, monkeypatch):
    """_dispatch 在沒有真正顯示器的測試情境下呼叫（self.logical 不存在）：
    _start_transition 必須安全跳過，不能炸掉。"""
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None, alarm_store=None)
    app._start_transition()
    assert app._transition.active() is False
    assert app._transition_start is None


# ---------------------------------------------------------------- weather_tick 節奏


def test_run_iteration_increments_weather_tick_once_per_second(tmp_path, monkeypatch):
    """凍結 datetime.datetime.now，不依賴真實掛鐘秒數邊界——直接呼叫
    _run_iteration() 會用真的 datetime.now()，若不凍結，測試在剛好跨過整數秒的
    瞬間會變成 flaky（曾實際觀察到）。凍結後可以精確控制「同一秒 vs 下一秒」。
    """
    # 防禦性重新初始化：pygame.event.get() 需要 video 子系統已初始化，若同一個
    # pytest session 裡有其他測試檔呼叫過 pygame.quit()（例如
    # test_alarm_overlay_headless.py）會把它關掉，這裡確保與執行順序無關。
    pygame.init()
    app = _make_dashboard_app(tmp_path, monkeypatch)
    clock = pygame.time.Clock()

    class _Frozen(datetime):
        current = NOW.replace(microsecond=0)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz is not None else cls.current

    monkeypatch.setattr("datetime.datetime", _Frozen)

    assert app._weather_tick == 0
    app._run_iteration(clock, True)
    assert app._weather_tick == 1

    app._run_iteration(clock, True)      # 時間沒動：仍是同一秒
    assert app._weather_tick == 1, "同一秒內第二次呼叫不該再 +1"

    _Frozen.current = _Frozen.current + timedelta(seconds=1)
    app._run_iteration(clock, True)      # 推進 1 秒
    assert app._weather_tick == 2, "跨過下一秒應該再 +1"


# ---------------------------------------------------------------- 開機 splash


def test_play_splash_skips_cleanly_when_no_splash_env_set(tmp_path, monkeypatch):
    """DESKBAR_NO_SPLASH=1 時應立刻返回，完全不去碰 self.logical/self.screen
    （這個測試情境下兩者都沒有設定，真的去畫就會 AttributeError）。"""
    monkeypatch.setenv("DESKBAR_NO_SPLASH", "1")
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None, alarm_store=None)
    app._play_splash()
