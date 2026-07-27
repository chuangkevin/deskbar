"""整合驗收（task-40）：把 weatherfx／presence／transitions 三條並行線接進
dashboard.py／app.py／settings_view.py 的實際掛載點是否生效。

個別模組自身的行為細節已由各自的測試檔覆蓋（test_weatherfx_headless.py／
test_presence.py／test_transitions_headless.py），這裡只驗證「掛載本身有沒有接對」：
presence 過濾＋鎖頭圖示、settings_view 開關鈕、app.py toggle_presence dispatch、
切換過場 SlideTransition 生命週期、天氣氛圍幀的重繪分支、開機 splash 可跳過。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
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


# ---------------------------------------------------------------- 右上角鎖頭圖示（已移除）


def test_presence_lock_icon_never_drawn():
    """2026-07-27 首日 UAT：右上鎖頭被誤認為異常狀態，使用者要求移除——
    任何 presence 狀態組合都不得在右上角畫鎖頭。"""
    for present in (True, False):
        settings = _settings_two_accounts()
        settings.presence_enabled = True
        settings.presence_hide_accounts = ["hidden@x.com"]
        st = _state_with_events()
        st.set_presence(PresenceState(present=present, rssi=None,
                                      last_seen=NOW if present else None, enabled=True))
        surf = _surf()
        dashboard.render(surf, st.snapshot(), settings, NOW)
        assert surf.get_at((1878, 30))[:3] == theme.C["bg"], "鎖頭不得再出現"


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


# ---------------------------------------------------------------- 天氣氛圍幀


def _freeze_now(monkeypatch) -> None:
    """凍結 datetime.datetime.now 在 NOW——氛圍測試靠「seq/minute 都沒變」走進
    idle 分支，不凍結的話測試恰好跨過整分鐘會誤觸全量重繪、變 flaky
    （weather_tick 時代就實際觀察過同型問題）。"""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW

    monkeypatch.setattr("datetime.datetime", _Frozen)


def _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61) -> App:
    """dashboard 頁、seq/minute 記帳已對齊（idle 狀態）、可選天氣資料的 App，
    _flip 換成計數器（app._flips），走到任何重繪分支都會留下痕跡。"""
    # 防禦性重新初始化：pygame.event.get() 需要 video 子系統已初始化，若同一個
    # pytest session 裡有其他測試檔呼叫過 pygame.quit()（例如
    # test_alarm_overlay_headless.py）會把它關掉，這裡確保與執行順序無關。
    pygame.init()
    _freeze_now(monkeypatch)
    app = _make_dashboard_app(tmp_path, monkeypatch)
    if weather_code is not None:
        from deskbar.weather import Weather
        app.state.set_weather(Weather(temp=31.0, code=weather_code, tmax=33.0,
                                      tmin=27.0, label="南港", fetched_at=NOW))
    app._last_seq = app.state.snapshot().seq
    app._last_minute = NOW.minute
    app._flips = []
    app._flip = lambda: app._flips.append(1)
    return app


def test_idle_dashboard_with_animated_weather_renders_ambient_frames(tmp_path, monkeypatch):
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    clock = pygame.time.Clock()
    app._run_iteration(clock, True)
    app._run_iteration(clock, True)
    assert len(app._flips) == 2, "資料/分鐘沒變也要逐幀重繪天氣場景（氛圍幀）"


def test_ambient_frame_only_touches_left_panel_pixels(tmp_path, monkeypatch):
    from deskbar.ui.dashboard import PANEL_W
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    sentinel = (7, 13, 29)
    app.logical.fill(sentinel)
    app._run_iteration(pygame.time.Clock(), True)
    assert app.logical.get_at((PANEL_W + 200, 240))[:3] == sentinel, \
        "氛圍幀不得重畫中欄行事曆"
    assert app.logical.get_at((1700, 240))[:3] == sentinel, "氛圍幀不得重畫右欄油表"
    changed = any(app.logical.get_at((x, 300))[:3] != sentinel
                  for x in range(0, PANEL_W, 8))
    assert changed, "左欄應該真的被重畫"


def test_no_ambient_render_without_weather_data(tmp_path, monkeypatch):
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=None)
    app._run_iteration(pygame.time.Clock(), True)
    assert app._flips == [], "沒有天氣資料就維持省電閒置，不該重繪"


def test_no_ambient_render_on_non_dashboard_views(tmp_path, monkeypatch):
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    app.view = "settings"
    app._run_iteration(pygame.time.Clock(), True)
    assert app._flips == [], "settings/alarms/detail 頁不跑氛圍幀"


def test_no_ambient_render_for_unanimated_weather_code(tmp_path, monkeypatch):
    """ANIMATED_CODES 防禦閘門的行為鎖：不明 code（open-meteo 契約外）維持
    tick(10) 省電閒置——突變實驗證實少了這條，把閘門改成恆真測試照樣全綠。"""
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=100)
    app._run_iteration(pygame.time.Clock(), True)
    assert app._flips == []


def test_no_ambient_render_on_detail_modal(tmp_path, monkeypatch):
    """detail 是疊在 dashboard 上的 modal（跟 settings 走完全不同的 render
    路徑）：氛圍幀若在 detail 頁跑，會逐幀重畫左欄、擦掉與左欄重疊的 modal
    暗幕。必須靜止。"""
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    app.view = "detail"
    app._run_iteration(pygame.time.Clock(), True)
    assert app._flips == []


def test_ambient_inactive_while_alarm_firing(tmp_path, monkeypatch):
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    app.firing = ["a"]
    assert app._ambient_active(app.state.snapshot()) is False


def test_flip_and_ambient_frames_share_live_weather_t(tmp_path, monkeypatch):
    """weather_t 的兩條接線（翻牌/全量重繪 → dashboard.render、氛圍幀 →
    render_panel_only）都必須吃活的單調秒數——突變實驗證實：把 _draw_frame 的
    weather_t=self._weather_t() 拿掉（回到預設 0.0），舊測試照樣全綠，但實機
    每逢整分翻牌天氣場景會跳回 t=0 再跳回 uptime，每分鐘閃一次。"""
    import time as _time
    app = _make_idle_dashboard_app(tmp_path, monkeypatch, weather_code=61)
    seen = []
    monkeypatch.setattr(dashboard, "render",
                        lambda *a, **k: seen.append(("full", k.get("weather_t", 0.0))) or [])
    monkeypatch.setattr(dashboard, "render_panel_only",
                        lambda surface, snap, settings, now, weather_t=0.0:
                        seen.append(("ambient", weather_t)))
    app._anim_start = _time.monotonic()
    app._clock_prev = "13:59"
    app._run_iteration(pygame.time.Clock(), True)      # 翻牌幀（全量重繪路徑）
    app._anim_start = None
    app._run_iteration(pygame.time.Clock(), True)      # 氛圍幀
    kinds = [k for k, _ in seen]
    assert "full" in kinds and "ambient" in kinds
    ts = [t for _, t in seen]
    assert all(t > 0.0 for t in ts), "兩條路徑都要傳活的 weather_t，不得回落到預設 0.0"
    assert ts == sorted(ts), "兩條路徑必須共用同一個單調時間基準"


def test_any_touch_dismisses_all_firing_alarms(tmp_path, monkeypatch):
    """響鈴中任何觸碰（含被拖曳判定吃掉的滑動）都要一次關掉全部鬧鐘：
    逐顆 pop＋拖曳門檻在實機上的體感就是「點了關不掉」。"""
    from deskbar.alarms import Alarm
    app = _make_dashboard_app(tmp_path, monkeypatch)
    app.firing = [Alarm(id="a", time="18:00", days=[], label="下班", enabled=True),
                  Alarm(id="b", time="18:00", days=[], label="備用", enabled=True)]
    app._drag_start = (500, 200)      # 模擬手指按下後滑動 >24px（原本會被當拖曳）
    app._handle_touch_up(560, 260)
    assert app.firing == [], "任何觸碰都要清空整個響鈴佇列"


def test_cycle_presence_speed_cycles_presets_and_saves(tmp_path, monkeypatch):
    """感應速度鈕：快(15/45)→中(30/90)→慢(45/150) 循環，間隔與緩衝連動並持久化。"""
    app = _make_app(tmp_path, monkeypatch)
    app.hits = settings_view.render(_surf(), app.state.snapshot(), app.settings, None)
    hit = next(h for h in app.hits if h.action == "cycle_presence_speed")
    assert (app.settings.presence_interval_sec, app.settings.presence_grace_sec) == (45, 150)
    seen = []
    for _ in range(3):
        app._dispatch(hit.rect.x + 2, hit.rect.y + 2)
        seen.append((app.settings.presence_interval_sec, app.settings.presence_grace_sec))
    assert seen == [(15, 45), (30, 90), (45, 150)]
    assert app._saved, "感應速度變更應呼叫 on_save 持久化"


def test_lanes_mode_renders_allday_events_as_tappable_pills():
    """河道模式整日事件回歸鎖：2026-07-27 頂欄膠囊移除後河道曾對整日事件
    全盲——個人日曆常以整日行程為主，看起來就像沒同步/整欄空白（實機當晚
    回報「個人行事曆完全沒有東西」）。整日事件必須以泳道頂膠囊呈現且可點。"""
    settings = _settings_two_accounts()
    st = AppState()
    st.set_events("open@x.com", [Event(
        "ad1", "open@x.com", "c", "整日待辦",
        NOW.replace(hour=0, minute=0), NOW.replace(hour=23, minute=59),
        True, None, None)], NOW)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    pills = [h for h in hits if h.action == "open_detail"
             and getattr(h.data, "id", None) == "ad1"]
    assert pills, "河道模式必須畫出整日事件膠囊（可點開詳情）"


def test_glass_rain_layer_renders_on_top_of_clock_cards():
    """HTC Sense 玻璃比喻的掛載驗證：雨天時 dashboard 左欄的時鐘卡區域，
    在「水滴積聚期」與「刷完乾淨期」要長得不一樣——證明水滴真的畫在時鐘
    之上（背景雨絲畫在卡片之前，蓋不到卡片，只有玻璃層蓋得到）。"""
    from deskbar.ui.weatherfx import WIPE_PERIOD_S
    from deskbar.weather import Weather
    settings = Settings()
    st = AppState()
    st.set_weather(Weather(temp=30.0, code=61, tmax=33.0, tmin=27.0,
                           label="南港", fetched_at=NOW))
    snap = st.snapshot()
    clock_zone = pygame.Rect(24, 34, 342, 96)     # flipclock 卡片帶
    surfs = []
    for t in (9.5, WIPE_PERIOD_S - 0.5):          # 積滿 vs 剛刷完
        s = _surf()
        dashboard.render_panel_only(s, snap, settings, NOW, t)
        surfs.append(pygame.image.tobytes(s.subsurface(clock_zone), "RGB"))
    assert surfs[0] != surfs[1], "水滴應該蓋在時鐘卡上（玻璃層）"


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


def test_narrow_lane_cards_show_vertical_title():
    """河道窄卡（30 分鐘行程 ≈45px 寬）直排標題回歸鎖：太窄看不到字被
    實機點名，窄而高的卡必須有直書文字；窄又矮的卡維持純色塊。"""
    import pygame as _pg
    from deskbar.ui import eventcard
    tall_with = _surf()
    eventcard.draw_card(tall_with, _pg.Rect(600, 60, 44, 170),
                        theme.ACCOUNT_COLORS[0][0], "站立會議",
                        "09:30 – 10:00")
    tall_blank = _surf()
    eventcard.draw_card(tall_blank, _pg.Rect(600, 60, 44, 170),
                        theme.ACCOUNT_COLORS[0][0], "", None)
    assert _pg.image.tobytes(tall_with, "RGB") != _pg.image.tobytes(tall_blank, "RGB"), \
        "窄而高的卡應該畫出直排標題"
    short_with = _surf()
    eventcard.draw_card(short_with, _pg.Rect(600, 60, 44, 36),
                        theme.ACCOUNT_COLORS[0][0], "站立會議", None)
    short_blank = _surf()
    eventcard.draw_card(short_blank, _pg.Rect(600, 60, 44, 36),
                        theme.ACCOUNT_COLORS[0][0], "", None)
    assert _pg.image.tobytes(short_with, "RGB") == _pg.image.tobytes(short_blank, "RGB"), \
        "窄又矮（<44px 高）維持純色塊"
