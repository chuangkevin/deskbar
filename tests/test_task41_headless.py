"""體感提速＋智慧儀表板批次（2026-07-30）：

- 按壓高亮／跟手預覽數學一致性／翻頁過場
- 深夜熄屏（brightness sleep window、觸摸喚醒、veil 全黑）
- 迫近行程搶焦點（自動切回行事曆、結束還原、使用者接管）
- Linear 磁碟快取 round-trip、卡片詳情浮層
- /api/screenshot 事件橋、/api/backup 祕密剔除、prefs 睡眠欄位＋bump
- 左欄下一行程倒數、右欄待辦摘要
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar import brightness
from deskbar.config import Settings
from deskbar.linear import LinearIssue
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 30, 10, 0, tzinfo=TZ)


def _issue(i, prio=0, due=None):
    return LinearIssue(identifier=f"SARA-{i}", title=f"待辦事項標題 {i}",
                       state_name="In Progress", state_type="started",
                       state_color="#5e6ad2", priority=prio, due=due, project="專案")


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _make_app(tmp_path, monkeypatch, **kw) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    app = App(AppState(), Settings(), threading.Lock(), on_save=lambda s: None, **kw)
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda *a, **k: None
    return app


# ---------------------------------------------------------------- 熄屏

def test_brightness_sleep_window_and_wake():
    s = Settings(sleep_enabled=True, sleep_start_min=60, sleep_end_min=390)
    assert brightness.effective(s, 120) == 0, "睡眠時段內＝熄屏"
    assert brightness.effective(s, 120, awake=True) > 0, "觸摸喚醒中忽略睡眠"
    assert brightness.effective(s, 600) > 0, "時段外照常"
    s2 = Settings(sleep_enabled=False, sleep_start_min=60, sleep_end_min=390)
    assert brightness.effective(s2, 120) > 0, "未啟用不熄屏"
    assert brightness.veil_alpha(0) == 255, "熄屏＝全黑"
    assert brightness.veil_alpha(100) == 0


def test_touch_down_during_sleep_wakes_and_swallows(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.sleep_enabled = True
    app.settings.sleep_start_min = 0
    app.settings.sleep_end_min = 1439      # 全天睡眠 → 必定熄屏
    assert app._screen_asleep() is True
    app._touch_down(960, 240)
    assert app._swallow_touch is True, "熄屏第一觸要吞掉"
    assert app._wake_until > 0
    assert app._screen_asleep() is False, "喚醒中不再算熄屏"
    app._touch_down(960, 240)
    assert app._drag_start is not None, "喚醒後的觸摸是正常操作"


# ---------------------------------------------------------------- 按壓回饋

def test_press_feedback_highlights_hit_and_cleans_up(tmp_path, monkeypatch):
    from deskbar.layout import Rect
    from deskbar.ui import Hit
    app = _make_app(tmp_path, monkeypatch)
    app.hits = [Hit(Rect(100, 100, 200, 80), "open_settings", None)]
    before = pygame.image.tobytes(app.logical, "RGB")
    app._press_feedback(150, 130)
    assert app._pressed_dirty is True
    assert pygame.image.tobytes(app.logical, "RGB") != before, "命中要立即畫高亮"
    app.view = "nonexistent"          # 讓 up 不真的 dispatch 出事
    app._handle_touch_up(150, 130)
    assert app._pressed_dirty is False and app._last_seq == -1, "放手要洗掉高亮"
    app2 = _make_app(tmp_path, monkeypatch)
    app2.hits = []
    base = pygame.image.tobytes(app2.logical, "RGB")
    app2._press_feedback(150, 130)
    assert app2._pressed_dirty is False
    assert pygame.image.tobytes(app2.logical, "RGB") == base, "沒命中不亂畫"


# ---------------------------------------------------------------- 跟手預覽

def test_pan_preview_math_matches_commit(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.view_anchor = NOW      # 固定錨點：排除兩次呼叫間 now() 的毫秒漂移
    preview = app._pan_anchor_from(-300, 1100)
    app._pan_view(-300, 1100)
    assert preview == app.view_anchor, "預覽與提交必須同一套數學"


# ---------------------------------------------------------------- 翻頁過場

def test_center_page_swipe_starts_transition(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.center_view = "linear"
    app.state.set_linear([_issue(i) for i in range(12)], NOW)   # 2 頁
    app._drag_start = (900, 200)
    app._handle_touch_up(700, 200)          # 往左滑 200px → 下一頁
    assert app.center_pages["linear"] == 1
    assert app._transition_start is not None, "翻成要播滑動過場"
    app._transition_start = None
    app._drag_start = (900, 200)
    app._handle_touch_up(700, 200)          # 已在最末頁 → 不動、不播
    assert app.center_pages["linear"] == 1
    assert app._transition_start is None, "邊界沒翻成不播過場"


# ---------------------------------------------------------------- 迫近搶焦點

def test_auto_center_switch_and_restore(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.center_view = "notes"
    ev = Event("e1", "a@x", "c", "站立會議", NOW + timedelta(minutes=10),
               NOW + timedelta(minutes=40), False, None, None)
    app.state.set_events("a@x", [ev], NOW)
    app._auto_center_tick(app.state.snapshot(), NOW)
    assert app.settings.center_view == "calendar", "迫近 10 分鐘要自動切回行事曆"
    assert app._auto_center_prev == "notes"
    later = NOW + timedelta(minutes=30)     # 開始 20 分鐘後＝不再迫近
    app._transition_start = None
    app._auto_center_tick(app.state.snapshot(), later)
    assert app.settings.center_view == "notes", "結束後要還原原本視圖"
    assert app._auto_center_prev is None


def test_auto_center_user_takeover_cancels(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.center_view = "linear"
    ev = Event("e1", "a@x", "c", "會", NOW + timedelta(minutes=5),
               NOW + timedelta(minutes=30), False, None, None)
    app.state.set_events("a@x", [ev], NOW)
    app._auto_center_tick(app.state.snapshot(), NOW)
    assert app.settings.center_view == "calendar"
    app.settings.ensure_account("a@x").calendars["c"] = True
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW)
    hit = next(h for h in app.hits if h.action == "toggle_center")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)   # 使用者手動切換＝接管
    assert app._auto_center_prev is None, "手動切換後自動還原取消"
    taken = app.settings.center_view                 # 使用者切到的視圖（linear）
    app._transition_start = None
    app._auto_center_tick(app.state.snapshot(), NOW + timedelta(seconds=5))
    assert app.settings.center_view == taken, \
        "迫近還在時不准再搶回去（實機回報：看便條一秒被踢回行事曆）"
    app._transition_start = None
    done = NOW + timedelta(minutes=30)               # 這一波過了
    app._auto_center_tick(app.state.snapshot(), done)
    assert app._auto_center_hold is False, "波次結束要解除 hold"
    ev2 = Event("e2", "a@x", "c", "下一場", done + timedelta(minutes=8),
                done + timedelta(minutes=38), False, None, None)
    app.state.set_events("a@x", [ev2], done)
    app._transition_start = None
    app._auto_center_tick(app.state.snapshot(), done)
    assert app.settings.center_view == "calendar", "下一波迫近恢復搶焦點"


def test_auto_center_ignores_allday(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.center_view = "notes"
    ev = Event("e1", "a@x", "c", "整日", NOW.replace(hour=0),
               NOW.replace(hour=0) + timedelta(days=1), True, None, None)
    app.state.set_events("a@x", [ev], NOW)
    app._auto_center_tick(app.state.snapshot(), NOW)
    assert app.settings.center_view == "notes", "整日事件不觸發搶焦點"


# ---------------------------------------------------------------- Linear 快取

def test_linear_cache_roundtrip(tmp_path, monkeypatch):
    from deskbar import linear as lin
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    items = [_issue(1, prio=1, due=date(2026, 8, 1)), _issue(2)]
    lin.save_cache(items, NOW)
    loaded, at = lin.load_cache()
    assert loaded == items and at == NOW, "快取 round-trip 要無損"
    assert lin.load_cache.__module__ == "deskbar.linear"


def test_linear_cache_missing_is_empty(tmp_path, monkeypatch):
    from deskbar import linear as lin
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path / "nope"))
    assert lin.load_cache() == ([], None)


# ---------------------------------------------------------------- 詳情浮層

def test_linear_card_detail_overlay_flow(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.settings.center_view = "linear"
    app.settings.linear_api_key = "lin_api_test"   # 沒 key 就不畫卡是既有契約
    app.state.set_linear([_issue(1, prio=1, due=date(2026, 7, 20))], NOW)
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW)
    hit = next(h for h in app.hits if h.action == "linear_detail")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert app.card_overlay is not None, "點卡要開詳情"
    from deskbar.ui import cardoverlay
    hits = cardoverlay.render(_surf(), app.card_overlay, NOW)
    assert len(hits) == 1 and hits[0].action == "overlay_close"
    app.hits = hits
    app._drag_start = (900, 200)
    app._handle_touch_up(600, 200)      # 浮層開著滑動＝關閉，不翻頁
    assert app.card_overlay is None
    assert app.center_pages["linear"] == 0


# ---------------------------------------------------------------- 截圖橋

def test_screenshot_bridge_service(tmp_path, monkeypatch):
    bridge = {"want": threading.Event(), "done": threading.Event(), "data": None}
    app = _make_app(tmp_path, monkeypatch, shot_bridge=bridge)
    bridge["want"].set()
    app._service_screenshot()
    assert bridge["done"].is_set() and not bridge["want"].is_set()
    assert bridge["data"][:8] == b"\x89PNG\r\n\x1a\n", "要吐合法 PNG"


def test_screenshot_endpoint_roundtrip(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    bridge = {"want": threading.Event(), "done": threading.Event(), "data": None}

    def fake_render_loop():
        assert bridge["want"].wait(2.0)
        bridge["data"] = b"\x89PNG\r\n\x1a\nfake"
        bridge["want"].clear()
        bridge["done"].set()

    t = threading.Thread(target=fake_render_loop, daemon=True)
    t.start()
    app = create_app(_FakeAlarms(), shot_bridge=bridge)
    app.config["TESTING"] = True
    c = app.test_client()
    r = c.get("/api/screenshot")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.data.startswith(b"\x89PNG")
    app2 = create_app(_FakeAlarms())
    app2.config["TESTING"] = True
    assert app2.test_client().get("/api/screenshot").status_code == 501


# ---------------------------------------------------------------- 備份

def test_backup_excludes_secret(tmp_path, monkeypatch):
    from deskbar import config as cfg
    from deskbar.notes import NotesStore
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings()
    s.linear_api_key = "lin_api_SECRET"
    cfg.save_settings(s)
    NotesStore().add("備份測試便條")
    app = create_app(_FakeAlarms())
    app.config["TESTING"] = True
    r = app.test_client().get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    body = r.get_json()
    assert body["settings"] is not None
    assert "linear_api_key" not in body["settings"], "祕密不進備份檔"
    assert "SECRET" not in r.get_data(as_text=True)
    assert body["notes"] and body["notes"][0]["text"] == "備份測試便條"


# ---------------------------------------------------------------- prefs 睡眠

def test_prefs_sleep_fields_and_bump(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings()
    state = AppState()
    lock = threading.Lock()
    app = create_app(_FakeAlarms(), settings_provider=s, settings_lock=lock,
                     on_save=lambda _s: None, usage_state=state)
    app.config["TESTING"] = True
    c = app.test_client()
    p = c.get("/api/prefs").get_json()
    assert {"sleep_enabled", "sleep_start_min", "sleep_end_min"} <= set(p)
    seq0 = state.snapshot().seq
    r = c.patch("/api/prefs", json={"sleep_enabled": True, "sleep_start_min": 90,
                                    "sleep_end_min": 420})
    assert r.status_code == 200
    assert (s.sleep_enabled, s.sleep_start_min, s.sleep_end_min) == (True, 90, 420)
    assert state.snapshot().seq > seq0, "prefs 改動要叫醒 render 迴圈"


# ---------------------------------------------------------------- 左欄倒數/右欄摘要

def test_next_event_picks_earliest_today():
    st = AppState()
    settings = Settings()
    ev_late = Event("e2", "a@x", "c", "晚的", NOW + timedelta(hours=5),
                    NOW + timedelta(hours=6), False, None, None)
    ev_soon = Event("e1", "a@x", "c", "早的", NOW + timedelta(minutes=30),
                    NOW + timedelta(hours=1), False, None, None)
    ev_past = Event("e0", "a@x", "c", "過了", NOW - timedelta(hours=1),
                    NOW - timedelta(minutes=10), False, None, None)
    ev_tmrw = Event("e3", "a@x", "c", "明天", NOW + timedelta(days=1),
                    NOW + timedelta(days=1, hours=1), False, None, None)
    st.set_events("a@x", [ev_late, ev_soon, ev_past, ev_tmrw], NOW)
    best = dashboard.next_event(st.snapshot(), settings, NOW)
    assert best is not None and best.id == "e1", "要挑今天接下來最早的計時行程"


def test_panel_countdown_and_right_mini_draw_pixels():
    st = AppState()
    settings = Settings()
    settings.ensure_account("a@x").calendars["c"] = True
    st.set_events("a@x", [Event("e1", "a@x", "c", "版更 Demo",
                                NOW + timedelta(minutes=40),
                                NOW + timedelta(minutes=90), False, None, None)], NOW)
    st.set_linear([_issue(1, prio=1, due=date(2026, 7, 30)), _issue(2), _issue(3)], NOW)
    a = _surf()
    dashboard.render(a, st.snapshot(), settings, NOW)
    b = _surf()
    empty = AppState()
    dashboard.render(b, empty.snapshot(), settings, NOW)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB"), \
        "倒數行＋待辦摘要要真的畫出東西"


# ---------------------------------------------------------------- 螢幕頁

def test_screen_view_has_sleep_controls():
    from deskbar.ui import screen_view
    s = _surf()
    hits = screen_view.render(s, Settings())
    fields = {h.data[0] for h in hits if h.action == "scr_adj"}
    assert {"sleep_start_min", "sleep_end_min"} <= fields, "睡眠時段要可調"
    assert any(h.action == "toggle_sleep" for h in hits), "要有睡眠開關"
    assert any(h.action == "rotate" for h in hits)


def test_toggle_sleep_dispatch(tmp_path, monkeypatch):
    from deskbar.ui import screen_view
    app = _make_app(tmp_path, monkeypatch)
    app.view = "screen"
    app.hits = screen_view.render(_surf(), app.settings)
    hit = next(h for h in app.hits if h.action == "toggle_sleep")
    assert app.settings.sleep_enabled is False
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert app.settings.sleep_enabled is True


# ---------------------------------------------------------------- 區域限定過場

def test_slide_transition_region_keeps_chrome_pixels():
    """過場只滑中欄內容：區域外（時鐘/油表/頂列）像素一顆都不准動。"""
    from deskbar.layout import Rect
    from deskbar.ui.transitions import SlideTransition
    area = Rect(402, 52, 1118, 428)
    old = pygame.Surface((1920, 480)); old.fill((8, 8, 8))
    pygame.draw.rect(old, (200, 40, 40), (500, 100, 300, 120))      # 舊中欄內容
    new = pygame.Surface((1920, 480)); new.fill((8, 8, 8))
    pygame.draw.rect(new, (40, 200, 40), (500, 100, 300, 120))      # 新中欄內容
    new.set_at((100, 240), (1, 2, 3))       # 左欄記號（區域外）
    new.set_at((1700, 240), (4, 5, 6))      # 右欄記號（區域外）
    new.set_at((900, 20), (7, 8, 9))        # 頂列記號（區域外）
    ref = pygame.image.tobytes(new.subsurface((0, 0, 400, 480)), "RGB")
    t = SlideTransition()
    t.start(old, 1, area=area)
    out = t.frame(new, SlideTransition.DURATION / 2)
    assert out.get_at((100, 240))[:3] == (1, 2, 3), "左欄不准動"
    assert out.get_at((1700, 240))[:3] == (4, 5, 6), "右欄不准動"
    assert out.get_at((900, 20))[:3] == (7, 8, 9), "頂列不准動"
    assert pygame.image.tobytes(out.subsurface((0, 0, 400, 480)), "RGB") == ref
    # 50% 時舊(紅)內容應該已滑到區域左半、仍看得到
    half = pygame.image.tobytes(out.subsurface(
        (int(area.x), int(area.y), int(area.w), int(area.h))), "RGB")
    assert b"\xc8\x28\x28" in half, "過場中要看得到舊內容"
    out2 = t.frame(new, SlideTransition.DURATION + 0.01)
    assert out2 is new and not t.active(), "過場結束直接回新畫面"


def test_app_transition_is_center_scoped(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._start_transition(+1)
    assert app._transition._area is not None, "app 的過場一律中欄限定"
    assert app._transition._area.x > 400 and app._transition._area.right <= 1520


# ---------------------------------------------------------------- 跟手帶狀位移

def test_pan_band_follows_finger_and_releases(tmp_path, monkeypatch):
    """拖曳＝已渲染畫面 1:1 位移（不逐幀重繪——Pi 上那是 8fps 橡皮筋感）。"""
    app = _make_app(tmp_path, monkeypatch)
    app.logical.fill((8, 8, 8))
    app.logical.set_at((1000, 240), (250, 10, 10))   # 中欄內容記號
    app.logical.set_at((100, 240), (1, 2, 3))        # 左欄 chrome 記號
    app._drag_start = (900, 200)
    app._drag_last = (700, 200)                       # 往左拖 200px
    app._pan_band_preview()
    assert app._pan_band is not None, "拖曳中要建立帶狀快照"
    assert app.logical.get_at((800, 240))[:3] == (250, 10, 10), "內容要跟手位移"
    assert app.logical.get_at((100, 240))[:3] == (1, 2, 3), "左欄不准動"
    app._handle_touch_up(700, 200)                    # 放手＝提交平移
    assert app._pan_band is None and app._last_seq == -1
    assert app.view_anchor is not None, "放手要提交錨點"


def test_transition_frame_renders_new_frame_only_once(tmp_path, monkeypatch):
    """過場期間「新畫面」只真正渲染一次，其餘幀純快照合成（30fps 的關鍵）。"""
    import time as _t
    app = _make_app(tmp_path, monkeypatch)
    calls = []
    app._draw_frame = lambda snap, now, clock_anim=None: calls.append(1)
    app._start_transition(+1)
    app._render_transition_frame(NOW)
    app._transition_start = _t.monotonic()   # 固定 elapsed，排除測試機速度干擾
    app._render_transition_frame(NOW)
    app._transition_start = _t.monotonic()
    app._render_transition_frame(NOW)
    assert len(calls) == 1, "過場期間新畫面只渲染一次"


# ---------------------------------------------------------------- 髒區域旋轉

@pytest.mark.parametrize("rotation", [90, 270])
def test_flip_dirty_rotation_matches_full(tmp_path, monkeypatch, rotation):
    """局部旋轉貼回快取的結果必須與整張重新旋轉逐 byte 相同——映射算錯會
    整條帶貼歪，這顆測試把兩個實機角度、多個髒矩形全部鎖死。"""
    from deskbar import transform as tr
    app = _make_app(tmp_path, monkeypatch)
    del app._flip                       # 還原真正的 _flip（_make_app 有 stub 掉）
    app._dev = False
    app.settings.rotation = rotation
    app.screen = pygame.Surface((480, 1920))
    monkeypatch.setattr(pygame.display, "flip", lambda: None)
    for i in range(0, 1920, 160):       # 鋪可辨識的圖樣
        pygame.draw.rect(app.logical, ((i * 7) % 255, (i * 13) % 255, 200),
                         (i, (i // 160) * 24 % 456, 120, 24))
    app._flip()                         # 全量：建立旋轉快取
    angle = tr.pygame_rotation_angle(rotation)
    for dirty in ((0, 0, 400, 480), (402, 52, 1118, 428), (1172, 2, 110, 48),
                  (37, 211, 313, 97)):
        pygame.draw.rect(app.logical, (dirty[0] % 255, 90, dirty[1] % 255),
                         dirty)         # 弄髒該區域
        app._flip(dirty)                # 局部旋轉貼回
        full = pygame.transform.rotate(app.logical, angle)
        assert pygame.image.tobytes(app._rot_cache, "RGB") == \
            pygame.image.tobytes(full, "RGB"), f"{rotation}° dirty={dirty} 映射歪了"


def test_text_surface_caches_and_clears_on_theme_change():
    theme.set_theme("dark")
    a = theme.text_surface("快取測試", 22, theme.C["text"], bold=True)
    b = theme.text_surface("快取測試", 22, theme.C["text"], bold=True)
    assert a is b, "同字串同款式要回同一張面"
    c = theme.text_surface("快取測試", 22, theme.C["muted"], bold=True)
    assert c is not a, "不同顏色是不同 key"
    theme.set_theme("dark")             # 換主題（即使同名）要清快取
    d = theme.text_surface("快取測試", 22, theme.C["text"], bold=True)
    assert d is not a, "set_theme 後快取要重建"
