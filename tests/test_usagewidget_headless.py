"""右欄 usage 油表（deskbar.ui.usagewidget）：三組渲染、分級顏色、
未連結/需重新登入狀態、以及右欄內容不越界（不早於 x=1540、不晚於 x=1900）。"""
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
          needs_login=False):
    return UsageInfo(
        session_pct=session_pct, session_resets_at=NOW + timedelta(hours=2, minutes=3),
        weekly_pct=weekly_pct, weekly_resets_at=NOW + timedelta(days=1, hours=4),
        fable_pct=fable_pct, fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=fetched_at if fetched_at is not None else NOW,
        needs_login=needs_login,
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


# ---------------------------------------------------------------- 三組渲染


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


# ---------------------------------------------------------------- 分級顏色


def _bar_fill_pixel(surf, group_index=0):
    x0 = 1540
    y = usagewidget.GROUP_START_Y + group_index * usagewidget.GROUP_STEP
    bar_x = x0 + usagewidget.BAR_MARGIN
    bar_y = y + 26
    return surf.get_at((bar_x + 5, bar_y + usagewidget.BAR_H // 2))[:3]


def test_bar_color_low_tier_under_60_percent():
    surf = _surf()
    usagewidget.render(surf, _usage(session_pct=50.0), NOW, 1540, 360)
    assert _bar_fill_pixel(surf) == theme.col((93, 202, 165))


def test_bar_color_mid_tier_60_to_85_percent():
    surf = _surf()
    usagewidget.render(surf, _usage(session_pct=70.0), NOW, 1540, 360)
    assert _bar_fill_pixel(surf) == theme.col((239, 169, 72))


def test_bar_color_warn_tier_above_85_percent():
    surf = _surf()
    usagewidget.render(surf, _usage(session_pct=90.0), NOW, 1540, 360)
    assert _bar_fill_pixel(surf) == theme.C["warn"]


# ---------------------------------------------------------------- 狀態：None／needs_login


def test_none_usage_shows_not_connected_hint():
    surf = _surf()
    usagewidget.render(surf, None, NOW, 1540, 360)
    bg = theme.C["bg"]
    has_ink = any(
        surf.get_at((x, 220))[:3] != bg for x in range(1540, 1900, 2))
    assert has_ink, "usage 未連結時應該在中央畫出提示文字"
    # None 狀態不畫任何橫條（第一組橫條理應存在的位置應該還是純背景色）。
    card_probe = surf.get_at((1540 + usagewidget.BAR_MARGIN + 5,
                              usagewidget.GROUP_START_Y + 26 + usagewidget.BAR_H // 2))[:3]
    assert card_probe == bg


def test_needs_login_shows_relogin_hint_in_warn_color():
    surf = _surf()
    usage = _usage(session_pct=None, weekly_pct=None, fable_pct=None, needs_login=True)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    warn = theme.C["warn"]
    has_warn_ink = any(
        surf.get_at((x, 220))[:3] == warn for x in range(1540, 1900, 2))
    assert has_warn_ink, "需重新登入時中央提示文字應為 warn 色"


def test_stale_fetched_at_shows_minutes_ago_note():
    surf = _surf()
    usage = _usage(fetched_at=NOW - timedelta(minutes=10))
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    has_ink = any(
        surf.get_at((x, usagewidget.TITLE_Y + 4))[:3] != bg
        for x in range(1700, 1900, 2))
    assert has_ink, "距上次更新超過 180 秒時，標題列右側應該加註「(N 分前)」"


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
