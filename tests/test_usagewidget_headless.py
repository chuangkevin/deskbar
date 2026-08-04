"""右欄 usage 油表（deskbar.ui.usagewidget）：Claude Code 與 Antigravity 兩區塊渲染、
分級顏色、未連結/需重新登入狀態、以及右欄內容不越界。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.claudeusage import UsageInfo
from deskbar.ui import theme, usagewidget

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _usage(session_pct=42.0, weekly_pct=61.0, fable_pct=12.0, fetched_at=None,
           ag_5h_pct=None, ag_weekly_pct=None):
    return UsageInfo(
        session_pct=session_pct, session_resets_at=NOW + timedelta(hours=2, minutes=3),
        weekly_pct=weekly_pct, weekly_resets_at=NOW + timedelta(days=1, hours=4),
        fable_pct=fable_pct, fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=fetched_at if fetched_at is not None else NOW,
        ag_5h_pct=ag_5h_pct, ag_5h_resets_at=NOW + timedelta(hours=3),
        ag_weekly_pct=ag_weekly_pct, ag_weekly_resets_at=NOW + timedelta(days=5),
    )


def _scan_ink_outside(surf, x_lo, x_hi, bg):
    """回傳落在 [x_lo, x_hi) 之外、卻畫了非背景色像素的 (x, y) 清單（應該永遠是空的）。"""
    bad = []
    w, h = surf.get_size()
    for y in range(0, h, 3):          # 抽樣掃描，夠密到抓出違規又不會太慢
        for x in list(range(0, x_lo, 5)) + list(range(x_hi, w, 5)):
            if surf.get_at((x, y))[:3] != bg:
                bad.append((x, y))
    return bad


# ---------------------------------------------------------------- 三組/兩區塊渲染


def test_render_three_groups_draws_ink_for_each_group():
    surf = _surf()
    usagewidget.render(surf, _usage(), NOW, 1540, 360)
    bg = theme.C["bg"]
    for i in range(3):     # 5H SESSION / 本週 / FABLE 三組的 label 列各抽一行檢查
        y = usagewidget.GROUP_START_Y + i * usagewidget.GROUP_STEP
        row_has_ink = any(
            surf.get_at((x, y + 8))[:3] != bg for x in range(1540, 1900, 2))
        assert row_has_ink, f"第 {i} 組應該畫出 label/百分比文字"


def test_fable_group_skipped_when_no_data():
    surf = _surf()
    usagewidget.render(surf, _usage(fable_pct=None), NOW, 1540, 360)
    bg = theme.C["bg"]
    third_y = usagewidget.GROUP_START_Y + 2 * usagewidget.GROUP_STEP
    row_has_ink = any(
        surf.get_at((x, third_y + 8))[:3] != bg for x in range(1540, 1900, 2))
    assert not row_has_ink, "FABLE 無資料時第三組不該畫任何東西"


def test_antigravity_section_rendered_when_ag_data_present():
    surf = _surf()
    usage = _usage(ag_5h_pct=64.24, ag_weekly_pct=94.04)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    ag_has_ink = any(
        surf.get_at((x, 212))[:3] != bg for x in range(1540, 1900, 2))
    assert ag_has_ink, "有 AG 資料時應該畫出 ANTIGRAVITY · GEMINI 標題區塊"


def test_antigravity_section_skipped_when_ag_data_is_none():
    surf = _surf()
    usage = _usage(ag_5h_pct=None, ag_weekly_pct=None)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    ag_has_ink = any(
        surf.get_at((x, y))[:3] != bg
        for y in range(195, 350, 4)
        for x in range(1540, 1900, 4)
    )
    assert not ag_has_ink, "AG 兩個 pct 皆 None 時完全不畫該區塊（含分隔線與標題）"


def test_layout_bottom_never_exceeds_y352():
    surf = _surf()
    usage = _usage(fable_pct=12.0, ag_5h_pct=64.24, ag_weekly_pct=94.04)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    overshoot = [
        (x, y)
        for y in range(353, 480, 2)
        for x in range(1540, 1900, 2)
        if surf.get_at((x, y))[:3] != bg
    ]
    assert not overshoot, f"版面最深超過 y=352：{overshoot[:10]}"


# ---------------------------------------------------------------- 分級顏色


def _bar_fill_pixel(surf, group_index=0):
    x0 = 1540
    y = usagewidget.GROUP_START_Y + group_index * usagewidget.GROUP_STEP
    bar_x = x0 + usagewidget.BAR_MARGIN
    bar_y = y + 24
    return surf.get_at((bar_x + 5, bar_y + usagewidget.BAR_H // 2))[:3]


def test_bar_color_normal_use_is_claude_orange():
    for pct in (20.0, 40.0, 55.0):
        surf = _surf()
        usagewidget.render(surf, _usage(session_pct=pct), NOW, 1540, 360)
        assert _bar_fill_pixel(surf) == theme.C["usage_bar"], pct


def test_bar_color_warn_tier_above_85_percent():
    surf = _surf()
    usagewidget.render(surf, _usage(session_pct=90.0), NOW, 1540, 360)
    assert _bar_fill_pixel(surf) == theme.C["usage_warn"]


# ---------------------------------------------------------------- 狀態：None／stale／very stale


def test_none_usage_shows_not_pushed_hint():
    surf = _surf()
    usagewidget.render(surf, None, NOW, 1540, 360)
    bg = theme.C["bg"]
    has_ink = any(
        surf.get_at((x, 220))[:3] != bg for x in range(1540, 1900, 2))
    assert has_ink, "usage 未推送時應該在中央畫出提示文字"
    card_probe = surf.get_at((1540 + usagewidget.BAR_MARGIN + 5,
                              usagewidget.GROUP_START_Y + 24 + usagewidget.BAR_H // 2))[:3]
    assert card_probe == bg


def test_stale_fetched_at_shows_minutes_ago_note():
    surf = _surf()
    usage = _usage(fetched_at=NOW - timedelta(minutes=10))   # 600s > STALE_AFTER_S(300)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    has_ink = any(
        surf.get_at((x, usagewidget.TITLE_Y + 4))[:3] != bg
        for x in range(1700, 1900, 2))
    assert has_ink, "距上次推送超過 300 秒時，標題列右側應該加註「(N 分前)」"


def test_fresh_fetched_at_shows_no_minutes_ago_note():
    surf = _surf()
    usage = _usage(fetched_at=NOW - timedelta(seconds=30))   # 遠低於 STALE_AFTER_S
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    has_ink = any(
        surf.get_at((x, usagewidget.TITLE_Y + 4))[:3] != bg
        for x in range(1700, 1900, 2))
    assert not has_ink, "剛推送不久不該顯示「(N 分前)」"


def test_very_stale_fetched_at_turns_bars_muted_gray():
    surf = _surf()
    fresh = _usage(session_pct=90.0)   # 90% 正常時應該是 usage_warn 色
    usagewidget.render(surf, fresh, NOW, 1540, 360)
    fresh_pixel = _bar_fill_pixel(surf)
    assert fresh_pixel == theme.C["usage_warn"]

    surf2 = _surf()
    stale = _usage(session_pct=90.0, fetched_at=NOW - timedelta(hours=2))   # > VERY_STALE_AFTER_S(3600)
    usagewidget.render(surf2, stale, NOW, 1540, 360)
    stale_pixel = _bar_fill_pixel(surf2)
    assert stale_pixel == theme.C["muted"], "超過 1 小時沒推送，橫條應該整組轉 muted 灰"


# ---------------------------------------------------------------- 不越界


def test_content_never_renders_left_of_x1540_or_right_of_x1900():
    surf = _surf()
    usagewidget.render(surf, _usage(), NOW, 1540, 360)
    bad = _scan_ink_outside(surf, 1540, 1900, theme.C["bg"])
    assert not bad, f"油表內容越界：{bad[:10]}"


def test_none_state_also_never_renders_outside_column():
    surf = _surf()
    usagewidget.render(surf, None, NOW, 1540, 360)
    bad = _scan_ink_outside(surf, 1540, 1900, theme.C["bg"])
    assert not bad, f"未連結狀態越界：{bad[:10]}"
