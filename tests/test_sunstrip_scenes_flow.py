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
    assert hits and hits[0].action == "toggle_center", "場景要留切走的逃生口"
    f1 = pygame.image.tobytes(s, "RGB")
    for t in (10.1, 10.2, 10.3):
        scenes.render(s, ui, NOW, t)
    assert pygame.image.tobytes(s, "RGB") != f1, "粒子要動"


def test_scene_reseeds_daily():
    ui = scenes.new_state()
    s = pygame.Surface((1920, 480))
    scenes.render(s, ui, NOW, 10.0)
    seed_a = ui["seed"]
    scenes.render(s, ui, NOW + timedelta(days=1), 10.1)
    assert ui["seed"] != seed_a, "每天要換一幅（種子含日序）"


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
