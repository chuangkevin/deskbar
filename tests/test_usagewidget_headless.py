"""右欄 usage 油表（deskbar.ui.usagewidget）：Claude Code、Antigravity 與 OpenAI 區塊渲染、
分級顏色、未連結/需重新登入狀態、以及右欄內容不越界。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.claudeusage import UsageInfo
from deskbar.ui import theme, usagewidget

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _usage(session_pct=42.0, weekly_pct=61.0, fable_pct=12.0, fetched_at=None,
           ag_5h_pct=None, ag_weekly_pct=None, oa_weekly_pct=None):
    return UsageInfo(
        session_pct=session_pct, session_resets_at=NOW + timedelta(hours=2, minutes=3),
        weekly_pct=weekly_pct, weekly_resets_at=NOW + timedelta(days=1, hours=4),
        fable_pct=fable_pct, fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=fetched_at if fetched_at is not None else NOW,
        ag_5h_pct=ag_5h_pct, ag_5h_resets_at=NOW + timedelta(hours=3),
        ag_weekly_pct=ag_weekly_pct, ag_weekly_resets_at=NOW + timedelta(days=5),
        oa_weekly_pct=oa_weekly_pct, oa_weekly_resets_at=NOW + timedelta(days=7),
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


def _rendered_texts(monkeypatch, usage):
    texts = []
    original = usagewidget._text

    def spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        texts.append(s)
        return original(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    monkeypatch.setattr(usagewidget, "_text", spy)
    surf = _surf()
    usagewidget.render(surf, usage, NOW, 1540, 360)
    return texts, surf


# ---------------------------------------------------------------- 三組/三區塊渲染


def test_render_three_groups_draws_ink_for_each_group():
    surf = _surf()
    usagewidget.render(surf, _usage(), NOW, 1540, 360)
    bg = theme.C["bg"]
    for i in range(3):     # 5H SESSION / 本週 / FABLE 三組的 label 列各抽一行檢查
        y = (usagewidget.TITLE_Y + usagewidget.SECTION_FIRST_GROUP
             + i * usagewidget.GROUP_STEP)
        row_has_ink = any(
            surf.get_at((x, y + 8))[:3] != bg for x in range(1540, 1900, 2))
        assert row_has_ink, f"第 {i} 組應該畫出 label/百分比文字"


def test_fable_group_skipped_when_no_data():
    surf = _surf()
    usagewidget.render(surf, _usage(fable_pct=None), NOW, 1540, 360)
    bg = theme.C["bg"]
    third_y = (usagewidget.TITLE_Y + usagewidget.SECTION_FIRST_GROUP
               + 2 * usagewidget.GROUP_STEP)
    row_has_ink = any(
        surf.get_at((x, third_y + 8))[:3] != bg for x in range(1540, 1900, 2))
    assert not row_has_ink, "FABLE 無資料時第三組不該畫任何東西"


def test_antigravity_section_rendered_when_ag_data_present(monkeypatch):
    texts, _ = _rendered_texts(monkeypatch, _usage(ag_5h_pct=64.24, ag_weekly_pct=94.04))
    assert "ANTIGRAVITY · GEMINI" in texts, "有 AG 資料時應該畫出 ANTIGRAVITY · GEMINI 標題區塊"


def test_all_three_sections_render_titles(monkeypatch):
    texts, _ = _rendered_texts(
        monkeypatch,
        _usage(ag_5h_pct=64.24, ag_weekly_pct=94.04, oa_weekly_pct=3.0),
    )
    assert "CLAUDE CODE" in texts
    assert "ANTIGRAVITY · GEMINI" in texts
    assert "OPENAI" in texts


def test_antigravity_section_skipped_when_ag_data_is_none(monkeypatch):
    texts, surf = _rendered_texts(
        monkeypatch,
        _usage(ag_5h_pct=None, ag_weekly_pct=None),
    )
    bg = theme.C["bg"]
    separator_has_ink = any(
        surf.get_at((x, 140))[:3] != bg for x in range(1540, 1901)
    )
    assert "ANTIGRAVITY · GEMINI" not in texts
    assert not separator_has_ink, "AG 兩個 pct 皆 None 時連分隔線也不該畫"


def test_openai_section_skipped_when_oa_data_is_none(monkeypatch):
    texts, surf = _rendered_texts(
        monkeypatch,
        _usage(ag_5h_pct=64.24, ag_weekly_pct=94.04, oa_weekly_pct=None),
    )
    bg = theme.C["bg"]
    separator_has_ink = any(
        surf.get_at((x, 246))[:3] != bg for x in range(1540, 1901)
    )
    assert "OPENAI" not in texts
    assert not separator_has_ink, "OpenAI 無資料時不該畫分隔線、標題或本週群組"


def test_full_layout_uses_expected_section_positions(monkeypatch):
    titles = []
    groups = []
    separators = []
    original_text = usagewidget._text
    original_line = pygame.draw.line

    def text_spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        if s in {"CLAUDE CODE", "ANTIGRAVITY · GEMINI", "OPENAI"}:
            titles.append((s, y, size))
        return original_text(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    def group_spy(surface, x0, w, y, label, pct, resets_at, now,
                  muted=False, window_s=None):
        groups.append((label, y))

    def line_spy(surface, color, start_pos, end_pos, width=1):
        if start_pos[1] == end_pos[1]:
            separators.append((start_pos, end_pos))
        return original_line(surface, color, start_pos, end_pos, width)

    monkeypatch.setattr(usagewidget, "_text", text_spy)
    monkeypatch.setattr(usagewidget, "_draw_group", group_spy)
    monkeypatch.setattr(pygame.draw, "line", line_spy)
    usagewidget.render(
        _surf(),
        _usage(ag_5h_pct=64.24, ag_weekly_pct=94.04, oa_weekly_pct=3.0),
        NOW, 1540, 360,
    )

    assert titles == [
        ("CLAUDE CODE", 2, 14),
        ("ANTIGRAVITY · GEMINI", 148, 14),
        ("OPENAI", 254, 14),
    ]
    assert groups == [
        ("5H SESSION", 22), ("本週", 62), ("FABLE", 102),
        ("5H", 168), ("本週", 208),
        ("本週", 274),
    ]
    assert separators == [((1540, 140), (1900, 140)),
                          ((1540, 246), (1900, 246))]


def test_layout_bottom_never_exceeds_y340():
    surf = _surf()
    usage = _usage(fable_pct=12.0, ag_5h_pct=64.24, ag_weekly_pct=94.04,
                   oa_weekly_pct=3.0)
    usagewidget.render(surf, usage, NOW, 1540, 360)
    bg = theme.C["bg"]
    ink_rows = [
        y for y in range(surf.get_height())
        if any(surf.get_at((x, y))[:3] != bg for x in range(1540, 1900))
    ]
    assert ink_rows
    assert max(ink_rows) <= 340, f"版面最深畫到 y={max(ink_rows)}"


def test_percentage_text_bottom_stays_above_bar(monkeypatch):
    pct_rect = None
    bar_tops = []
    original_text = usagewidget._text
    original_rect = pygame.draw.rect

    def text_spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        nonlocal pct_rect
        rect = original_text(surface, s, size, color, x, y, anchor=anchor, bold=bold)
        if s == "100%":
            pct_rect = rect
        return rect

    def rect_spy(surface, color, rect, *args, **kwargs):
        bar_tops.append(pygame.Rect(rect).top)
        return original_rect(surface, color, rect, *args, **kwargs)

    monkeypatch.setattr(usagewidget, "_text", text_spy)
    monkeypatch.setattr(pygame.draw, "rect", rect_spy)
    usagewidget._draw_group(
        _surf(), 1540, 360, 22, "5H SESSION", 100.0,
        NOW + timedelta(hours=1), NOW,
    )

    assert pct_rect is not None
    assert bar_tops
    assert pct_rect.bottom < min(bar_tops), (
        f"百分比文字底部 {pct_rect.bottom} 必須與橫條頂端 {min(bar_tops)} 保持間距"
    )


# ---------------------------------------------------------------- 分級顏色


def _bar_fill_pixel(surf, group_index=0):
    x0 = 1540
    y = (usagewidget.TITLE_Y + usagewidget.SECTION_FIRST_GROUP
         + group_index * usagewidget.GROUP_STEP)
    bar_x = x0 + usagewidget.BAR_MARGIN
    bar_y = y + 19
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


def test_none_usage_leaves_column_blank():
    surf = _surf()
    usagewidget.render(surf, None, NOW, 1540, 360)
    bg = theme.C["bg"]
    assert not any(surf.get_at((x, y))[:3] != bg
                   for x in range(1540, 1900, 2) for y in range(0, 480, 2))


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


def test_per_source_selection_and_24h_expiry(monkeypatch):
    usage = _usage(ag_5h_pct=20.0, ag_weekly_pct=30.0, oa_weekly_pct=5.0)
    usage = UsageInfo(**{**usage.__dict__,
        "claude_fetched_at": NOW - timedelta(hours=24),
        "ag_fetched_at": NOW - timedelta(hours=24, seconds=1),
        "oa_fetched_at": NOW - timedelta(minutes=1),
    })
    sections = usagewidget.visible_sections(usage, NOW)
    assert [title for title, _groups, _age in sections] == ["OPENAI"]
    assert usagewidget.visible_sections(usage, NOW, ["claude"]) == []
    texts, _ = _rendered_texts(monkeypatch, usage)
    assert "OPENAI" in texts and "CLAUDE CODE" not in texts


def test_ag_oa_do_not_inherit_claude_global_freshness(monkeypatch):
    """缺 ag/oa_fetched_at 時不可拿 Claude/全域 fetched_at 當年齡（會誤標 544 分前）。"""
    stale_claude = NOW - timedelta(minutes=544)
    usage = UsageInfo(
        session_pct=42.0, session_resets_at=NOW + timedelta(hours=2),
        weekly_pct=61.0, weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=None, fable_resets_at=None,
        fetched_at=stale_claude,
        claude_fetched_at=stale_claude,
        ag_5h_pct=20.0, ag_5h_resets_at=NOW + timedelta(hours=3),
        ag_weekly_pct=30.0, ag_weekly_resets_at=NOW + timedelta(days=5),
        oa_weekly_pct=5.0, oa_weekly_resets_at=NOW + timedelta(days=7),
        ag_fetched_at=None,
        oa_fetched_at=None,
    )
    sections = {title: age for title, _groups, age in usagewidget.visible_sections(usage, NOW)}
    assert sections["CLAUDE CODE"] == pytest.approx(544 * 60)
    assert sections["ANTIGRAVITY · GEMINI"] == 0.0
    assert sections["OPENAI"] == 0.0

    ages = []
    original_text = usagewidget._text

    def text_spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        if s.startswith("(") and "分前" in s:
            ages.append(s)
        return original_text(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    monkeypatch.setattr(usagewidget, "_text", text_spy)
    usagewidget.render(_surf(), usage, NOW, 1540, 360)
    assert ages == ["(544 分前)"], "只有 Claude 該顯示全域過期註記，AG/OA 不可跟風"


def test_per_source_age_label_uses_own_timestamp(monkeypatch):
    """有分來源時間戳時，AG/OA 各自顯示自己的「N 分前」。"""
    usage = UsageInfo(
        session_pct=42.0, session_resets_at=NOW + timedelta(hours=2),
        weekly_pct=61.0, weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=None, fable_resets_at=None,
        fetched_at=NOW - timedelta(hours=2),
        claude_fetched_at=NOW - timedelta(hours=2),
        ag_5h_pct=20.0, ag_5h_resets_at=NOW + timedelta(hours=3),
        ag_weekly_pct=30.0, ag_weekly_resets_at=NOW + timedelta(days=5),
        oa_weekly_pct=5.0, oa_weekly_resets_at=NOW + timedelta(days=7),
        ag_fetched_at=NOW - timedelta(minutes=12),
        oa_fetched_at=NOW - timedelta(seconds=30),
    )
    sections = {title: age for title, _groups, age in usagewidget.visible_sections(usage, NOW)}
    assert sections["ANTIGRAVITY · GEMINI"] == pytest.approx(12 * 60)
    assert sections["OPENAI"] == pytest.approx(30)

    notes = []
    original_text = usagewidget._text

    def text_spy(surface, s, size, color, x, y, anchor="topleft", bold=False):
        if s.startswith("(") and "分前" in s:
            notes.append(s)
        return original_text(surface, s, size, color, x, y, anchor=anchor, bold=bold)

    monkeypatch.setattr(usagewidget, "_text", text_spy)
    usagewidget.render(_surf(), usage, NOW, 1540, 360)
    assert "(120 分前)" in notes  # Claude
    assert "(12 分前)" in notes    # Antigravity
    assert not any(s == "(0 分前)" for s in notes)


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
