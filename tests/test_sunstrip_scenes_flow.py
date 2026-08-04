"""日光儀（sunstrip）/氛圍場景（scenes）/忙閒排程（UsageActivity+flow_target）
的 headless 測試。"""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from datetime import date, datetime, timedelta

import pygame
pygame.init()

from deskbar.claudeusage import (BUSY_WINDOW_S, SCENE_AFTER_S, UsageActivity,
                                 UsageInfo, flow_target)
from deskbar.ui import scenes, sunstrip, theme
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 3, 15, 0, tzinfo=TZ)


# ---------------------------------------------------------------- 日光儀

def test_sun_times_taipei_four_seasons():
    """NOAA 計算 vs 已知台北日出日落（±12 分鐘容差）。"""
    cases = [(date(2026, 8, 3), (5, 24), (18, 37)),
             (date(2026, 12, 21), (6, 34), (17, 7)),
             (date(2026, 3, 20), (6, 0), (18, 7)),
             (date(2026, 6, 21), (5, 5), (18, 47))]
    for d, (rh, rm), (sh, sm) in cases:
        rise, sset = sunstrip.sun_times(d, 25.046, 121.517, TZ)
        for got, exp_h, exp_m in ((rise, rh, rm), (sset, sh, sm)):
            diff = abs((got - got.replace(hour=exp_h, minute=exp_m))
                       .total_seconds())
            assert diff <= 12 * 60, f"{d} 算出 {got:%H:%M} 差太多"


def test_sunstrip_marker_moves_and_prefers_api_times():
    a, b = pygame.Surface((1920, 480)), pygame.Surface((1920, 480))
    sunstrip.draw(a, NOW, 25.046, 121.517)
    sunstrip.draw(b, NOW.replace(hour=22), 25.046, 121.517)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB"), \
        "不同時刻光點/配色要不同"
    # API 真值優先：給一組明顯不同的日出日落，帶子要重烤
    c = pygame.Surface((1920, 480))
    sunstrip.draw(c, NOW, 25.046, 121.517,
                  rise=NOW.replace(hour=9, minute=0),
                  sset=NOW.replace(hour=15, minute=30))
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(c, "RGB"), \
        "open-meteo 真值要蓋過天文計算"


def test_sunstrip_band_only_touches_top_rows():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    base = pygame.image.tobytes(s.subsurface((0, sunstrip.BAND_H + 4, 1920,
                                              400)), "RGB")
    sunstrip.draw(s, NOW, 25.046, 121.517)
    after = pygame.image.tobytes(s.subsurface((0, sunstrip.BAND_H + 4, 1920,
                                               400)), "RGB")
    assert base == after, "日光帶不得畫出頂緣區域之外"


# ---------------------------------------------------------------- 場景

def test_scene_renders_and_animates():
    ui = scenes.new_state()
    s = pygame.Surface((1920, 480))
    hits = scenes.render(s, ui, NOW, 10.0)
    assert hits and hits[0].action == "scene_tap", "場景要留 scene_tap 逃生口"
    f1 = pygame.image.tobytes(s, "RGB")
    for t in (10.1, 10.2, 10.3):
        scenes.render(s, ui, NOW, t)
    assert pygame.image.tobytes(s, "RGB") != f1, "畫面要動"


def test_every_scene_kind_renders_and_moves():
    """九個場景逐一冒煙：能畫、會動、跨晝夜不炸。"""
    s = pygame.Surface((1920, 480))
    for kind in scenes.SCENE_KEYS if hasattr(scenes, "SCENE_KEYS") else []:
        pass
    from deskbar.config import SCENE_KEYS
    for kind in SCENE_KEYS:
        for hour in (3, 12, 18):
            ui = scenes.new_state()
            now = NOW.replace(hour=hour)
            scenes.render(s, ui, now, 50.0, enabled=[kind])
            assert ui["kind"] == kind, "enabled 只給一個就只能挑那個"
            a = pygame.image.tobytes(s, "RGB")
            for t in (50.1, 50.2, 50.4, 50.8):
                scenes.render(s, ui, now, t, enabled=[kind])
            assert pygame.image.tobytes(s, "RGB") != a, f"{kind}@{hour} 要會動"


def test_scene_rotates_after_timeout_and_respects_enabled():
    ui = scenes.new_state()
    s = pygame.Surface((1920, 480))
    scenes.render(s, ui, NOW, 10.0, enabled=["ink", "stars"])
    assert ui["kind"] in ("ink", "stars")
    scenes.render(s, ui, NOW, 10.0 + scenes.ROTATE_S + 1,
                  enabled=["ink", "stars"])
    assert ui["kind"] in ("ink", "stars")
    # 勾選清單縮小後，下一幀立刻換到合法場景
    scenes.render(s, ui, NOW, 10.0 + scenes.ROTATE_S + 2, enabled=["fireflies"])
    assert ui["kind"] == "fireflies", "kind 不在 enabled 內要立即改挑"


# ---------------------------------------------------------------- 忙/閒

def _info(s=10.0, w=20.0, f=5.0):
    return UsageInfo(s, None, w, None, f, None, NOW)


def test_usage_activity_busy_and_idle():
    ua = UsageActivity()
    ua.feed(_info(10.0), 0.0)
    assert not ua.busy(0.0), "只有一筆基準還不算活動"
    ua.feed(_info(10.5), 60.0)                       # session_pct 上升＝在忙
    assert ua.busy(60.0)
    assert not ua.busy(60.0 + BUSY_WINDOW_S + 1), "窗外無新增量＝轉閒"


def test_usage_activity_reset_drop_is_not_activity():
    ua = UsageActivity()
    ua.feed(_info(80.0), 0.0)
    ua.feed(_info(2.0), 60.0)                        # 視窗重置的下降
    assert not ua.busy(60.0), "百分比下降不是使用者活動"
    ua.feed(_info(None, None, None), 120.0)          # agent 缺值不炸
    assert not ua.busy(120.0)


def test_usage_activity_scene_ready_needs_sustained_busy():
    ua = UsageActivity()
    ua.feed(_info(10.0), 0.0)
    ua.feed(_info(11.0), 10.0)
    assert not ua.scene_ready(10.0), "剛開始忙不切場景"
    ua.feed(_info(12.0), 10.0 + SCENE_AFTER_S)       # 持續有增量
    assert ua.scene_ready(10.0 + SCENE_AFTER_S), "忙滿門檻才 scene_ready"


def test_flow_target_table():
    assert flow_target(True, True, True) == "scene"
    assert flow_target(False, True, True) is None, "忙但未滿門檻＝不動"
    assert flow_target(False, False, True) == "notes"
    assert flow_target(False, False, False) == "calendar"


# ---------------------------------------------------------------- force 模式

def test_force_mode_tap_returns_then_auto_back(tmp_path, monkeypatch):
    import threading
    import time as _time
    from deskbar.config import Settings
    from deskbar.store import AppState
    from deskbar.ui import dashboard
    from deskbar.ui.app import App, FORCE_SCENE_RETURN_S
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    app = App(AppState(), Settings(), threading.Lock(), on_save=lambda s: None)
    app.settings.scene_mode = "force"
    app.settings.center_view = "scene"
    app.view = "dashboard"
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda *a, **k: None
    app.hits = dashboard.render(app.logical, app.state.snapshot(), app.settings,
                                NOW, scene_ui=app.scene_ui)
    hit = next(h for h in app.hits if h.action == "scene_tap")
    app._dispatch(hit.rect.x + 30, hit.rect.y + 30)
    assert app.settings.center_view == "calendar", "點場景＝回行事曆"
    assert app._force_scene_at > _time.monotonic(), "並排定回場景的時刻"
    app._check_force_scene(_time.monotonic())
    assert app.settings.center_view == "calendar", "一分鐘未到不搶回"
    app._check_force_scene(_time.monotonic() + FORCE_SCENE_RETURN_S + 1)
    assert app.settings.center_view == "scene", "時間到自動回場景"


def test_scene_settings_persist_and_validate(tmp_path, monkeypatch):
    import json
    from deskbar import config
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.Settings()
    s.scene_mode = "force"
    s.scenes_enabled = ("ink", "train")
    config.save_settings(s)
    s2 = config.load_settings()
    assert s2.scene_mode == "force" and s2.scenes_enabled == ("train", "ink"), \
        "載入時按 SCENE_KEYS 的 canonical 順序正規化"
    # 竄改檔案塞未知場景/未知模式 → 載入時過濾
    p = tmp_path / "settings.json"
    raw = json.loads(p.read_text())
    raw["scene_mode"] = "yolo"
    raw["scenes_enabled"] = ["ink", "not_a_scene"]
    p.write_text(json.dumps(raw))
    s3 = config.load_settings()
    assert s3.scene_mode == "auto" and s3.scenes_enabled == ("ink",)
    raw["scenes_enabled"] = []
    p.write_text(json.dumps(raw))
    assert config.load_settings().scenes_enabled == config.DEFAULT_SCENES, \
        "全反勾＝退回已驗收的預設輪播"


# ---------------------------------------------------------------- usage 配速

def test_usage_pace_and_over_pace():
    from deskbar.claudeusage import WINDOW_S, over_pace, pace_pct
    week = WINDOW_S["weekly"]
    resets = NOW + timedelta(days=5)                 # 已過 2/7
    pace = pace_pct(resets, NOW, week)
    assert abs(pace - 200 / 7) < 0.5, "過了兩天＝配速約 28.6%"
    assert over_pace(50.0, resets, NOW, week), "兩天燒 50% ＝超速轉紅"
    assert not over_pace(20.0, resets, NOW, week), "低於配速不轉紅"
    assert not over_pace(31.0, resets, NOW, week), "配速+5 緩衝內不轉紅"
    fresh = NOW + timedelta(days=7)                  # 視窗剛重置
    assert not over_pace(4.0, fresh, NOW, week), "剛重置的小額使用不該嚇人"
    assert not over_pace(50.0, None, NOW, week), "沒 resets_at 就不判"


def test_usage_widget_over_pace_draws_red():
    from deskbar.claudeusage import UsageInfo
    from deskbar.ui import theme, usagewidget
    over = UsageInfo(10.0, NOW + timedelta(hours=4), 50.0,
                     NOW + timedelta(days=5), None, None, NOW)
    ok = UsageInfo(10.0, NOW + timedelta(hours=4), 20.0,
                   NOW + timedelta(days=5), None, None, NOW)
    a, b = pygame.Surface((1920, 480)), pygame.Surface((1920, 480))
    usagewidget.render(a, over, NOW)
    usagewidget.render(b, ok, NOW)
    warn = theme.C["usage_warn"]
    reds_a = sum(1 for x in range(1560, 1880, 4) for y in range(80, 150, 2)
                 if a.get_at((x, y))[:3] == warn)
    reds_b = sum(1 for x in range(1560, 1880, 4) for y in range(80, 150, 2)
                 if b.get_at((x, y))[:3] == warn)
    assert reds_a > 0 and reds_b == 0, "超速的那條要轉紅、正常配速不紅"


def test_cumulus_assets_have_fully_transparent_borders():
    """防回歸：雲素材四邊 alpha 必須全 0——fBm 密度被 bbox 硬切的直邊在
    白色翻牌卡上會顯形成「奇怪的方塊」（2026-08-03 實機三次驗收的病灶）。"""
    import numpy as np
    from pathlib import Path
    base = Path("deskbar/assets/scenes")
    for name in ("cumulus_0", "cumulus_1"):
        s = pygame.image.load(str(base / f"{name}.png"))
        a = pygame.surfarray.pixels_alpha(s)
        edges = np.concatenate([a[0, :], a[-1, :], a[:, 0], a[:, -1]])
        assert edges.max() == 0, f"{name} 邊界 alpha 未歸零"
