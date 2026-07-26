"""三欄版面（左＝時鐘/日期/天氣/同步狀態，中＝行事曆時間軸，右＝Claude usage 油表）
的座標不重疊驗收：左欄內容不越過 PANEL_W、中欄 hits 落在 TL_X0..TL_X1、usage 欄
內容不早於 USAGE_X0、欄與欄之間的留白區塊維持乾淨，以及既有核心控制 hits 仍在。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard, theme

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 37, tzinfo=TZ)   # 週一

LEFT_PANEL_ACTIONS = {"open_alarms", "force_sync", "open_settings"}


def _surf():
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def _settings_with_account():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def _busy_state(n_days=7, long_title=True) -> AppState:
    """鋪滿長標題事件＋大量整日事件，盡量逼出「內容溢出欄位」的邊界情況。"""
    st = AppState()
    midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    title = "超級霹靂無敵冗長會議標題文字測試溢出" if long_title else "會議"
    events = []
    for d in range(n_days):
        day = midnight + timedelta(days=d)
        for h in range(8, 20, 2):
            events.append(Event(f"e{d}-{h}", "a@x.com", "c", f"{title}{d}-{h}",
                                day.replace(hour=h), day.replace(hour=h + 1),
                                False, None, None))
        events.append(Event(f"ad{d}", "a@x.com", "c", f"整日{title}{d}",
                            day, day + timedelta(days=1), True, None, None))
    st.set_events("a@x.com", events, NOW)
    return st


def _scan_column_clean(surf, x_lo, x_hi, bg):
    """回傳 [x_lo, x_hi) 這個直向窄帶內、非背景色的像素座標清單（應為空）。"""
    bad = []
    w, h = surf.get_size()
    assert 0 <= x_lo < x_hi <= w
    for y in range(0, h, 2):
        for x in range(x_lo, x_hi):
            if surf.get_at((x, y))[:3] != bg:
                bad.append((x, y))
    return bad


# ---------------------------------------------------------------- 核心控制 hits 仍在


def test_core_control_hits_still_present_in_3col_layout():
    settings = _settings_with_account()
    st = _busy_state()
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    for expected in ("cycle_span", "cycle_view_mode", "force_sync", "open_settings",
                     "open_alarms"):
        assert expected in actions, f"缺少核心控制 hit：{expected}"


# ---------------------------------------------------------------- 左欄內容不越界


def test_left_panel_hits_stay_within_panel_w():
    settings = _settings_with_account()
    st = _busy_state()
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    left_hits = [h for h in hits if h.action in LEFT_PANEL_ACTIONS]
    assert left_hits, "左欄應該至少有 open_alarms/force_sync/open_settings 三個 hit"
    for h in left_hits:
        assert h.rect.x + h.rect.w <= dashboard.PANEL_W, \
            f"{h.action} 的 hit 越過左欄右界 PANEL_W={dashboard.PANEL_W}：{h.rect}"


# ---------------------------------------------------------------- 中欄 hits 落在 TL_X0..TL_X1


def test_mid_column_hits_within_tl_bounds_lanes_mode():
    settings = _settings_with_account()
    st = _busy_state()
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    mid_hits = [h for h in hits if h.action not in LEFT_PANEL_ACTIONS]
    assert mid_hits
    for h in mid_hits:
        assert h.rect.x >= dashboard.TL_X0 - 1e-6, f"{h.action} 落在中欄左界之外：{h.rect}"
        assert h.rect.x + h.rect.w <= dashboard.TL_X1 + 1e-6, \
            f"{h.action} 越過中欄右界 TL_X1={dashboard.TL_X1}：{h.rect}"


def test_mid_column_hits_within_tl_bounds_week_month_agenda():
    settings = _settings_with_account()
    st = _busy_state()
    for span in ("week", "month"):
        for mode in ("lanes", "agenda"):
            settings.view_span = span
            settings.view_mode = mode
            hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
            mid_hits = [h for h in hits if h.action not in LEFT_PANEL_ACTIONS]
            assert mid_hits, f"span={span} mode={mode} 應該至少有中欄 hit"
            for h in mid_hits:
                assert h.rect.x >= dashboard.TL_X0 - 1e-6, \
                    f"span={span} mode={mode} {h.action} 落在中欄左界之外：{h.rect}"
                assert h.rect.x + h.rect.w <= dashboard.TL_X1 + 1e-6, \
                    f"span={span} mode={mode} {h.action} 越過中欄右界：{h.rect}"


def test_agenda_seven_columns_hits_stay_inside_narrow_mid_column():
    """agenda 模式 7 欄（week/month）在縮窄後的中欄（寬 1100，每欄約 157px）下，
    open_detail 逐行 hit 仍必須完全落在 TL_X0..TL_X1 內。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    settings.view_mode = "agenda"
    st = _busy_state()
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    assert detail_hits
    for h in detail_hits:
        assert h.rect.x >= dashboard.TL_X0 - 1e-6
        assert h.rect.x + h.rect.w <= dashboard.TL_X1 + 1e-6


# ---------------------------------------------------------------- usage 欄不產生 hits、內容不早於 USAGE_X0


def test_usage_column_never_produces_hits():
    settings = _settings_with_account()
    st = _busy_state()
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    for h in hits:
        assert h.rect.x < dashboard.USAGE_X0, \
            f"usage 欄不該有任何互動 hit，但 {h.action} 落在 {h.rect}"


def test_usage_widget_content_starts_at_or_after_usage_x0():
    from deskbar.claudeusage import UsageInfo
    settings = _settings_with_account()
    st = _busy_state()
    st.set_usage(UsageInfo(42.0, NOW + timedelta(hours=2), 61.0, NOW + timedelta(days=1),
                           12.0, NOW + timedelta(hours=1), NOW, needs_login=False))
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    bg = theme.C["bg"]
    bad = [(x, y) for y in range(0, 480, 4) for x in range(0, dashboard.USAGE_X0, 4)
          if x > dashboard.TL_X1 and surf.get_at((x, y))[:3] != bg]
    assert not bad, f"usage 內容不該早於 USAGE_X0={dashboard.USAGE_X0}：{bad[:10]}"


# ---------------------------------------------------------------- 欄與欄間留白乾淨（無內容跨欄溢出）


def test_gap_between_left_panel_and_mid_column_stays_clean():
    """PANEL_W(400) 與 TL_X0(420) 之間的 20px 留白：扣掉 x=PANEL_W 上那條 1px
    分隔線，其餘應該是純背景色，不該有任何欄位內容滲進來。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    settings.view_mode = "agenda"
    st = _busy_state()
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    bad = _scan_column_clean(surf, dashboard.PANEL_W + 2, dashboard.TL_X0, theme.C["bg"])
    assert not bad, f"左欄／中欄留白區被畫到了：{bad[:10]}"


def test_gap_between_mid_column_and_usage_column_stays_clean():
    """TL_X1(1520) 與 USAGE_X0(1540) 之間的 20px 留白，同上邏輯。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    settings.view_mode = "agenda"
    st = _busy_state()
    st.set_usage(None)
    surf = _surf()
    dashboard.render(surf, st.snapshot(), settings, NOW)
    bad = _scan_column_clean(surf, dashboard.TL_X1 + 2, dashboard.USAGE_X0, theme.C["bg"])
    assert not bad, f"中欄／右欄留白區被畫到了：{bad[:10]}"


# ---------------------------------------------------------------- 整日 chips 仍守 CHIP_MAX_X


