"""右欄：Claude Code、Antigravity (Gemini) 與 OpenAI usage 油表。

全寬單欄、由上到下三區：
1. CLAUDE CODE 區：5H SESSION / 本週 / FABLE（FABLE 無資料時略過）
2. ANTIGRAVITY · GEMINI 區：5H / 本週（無資料時整區略過，不畫分隔線與標題）
3. OPENAI 區：本週（無資料時整區略過，不畫分隔線與標題）

usage 資料完全被動接收：Mac agent POST 到 deskbar 的 /api/usage。

2026-08-10 實機確認：舊三行制造成文字與橫條重疊；每組因此固定改為文字一行、橫條一行。
"""
from __future__ import annotations

from datetime import datetime

import pygame

from deskbar.claudeusage import WINDOW_S, fmt_countdown, over_pace, pace_pct
from deskbar.ui import theme

TITLE_Y = 2
SECTION_FIRST_GROUP = 20
GROUP_STEP = 40
SECTION_SEP_GAP = 10
SECTION_TITLE_GAP = 8
BAR_H = 9
BAR_RADIUS = 4
BAR_MARGIN = 0            # 橫條滿寬，讓獨立的第二行清楚呈現可用範圍。
BAR_Y_OFFSET = 19         # 文字列完整結束後再起橫條，避免字框與橫條相貼。
STALE_AFTER_S = 300       # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」
VERY_STALE_AFTER_S = 3600 # 超過這麼久，整組轉 muted 灰（agent 可能已經停了）
HIDE_AFTER_S = 24 * 60 * 60
DEFAULT_SOURCES = ("claude", "antigravity", "openai")


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _center_text(surface, s, size, color, x0, w, cy):
    img = theme.text_surface(s, size, color)
    surface.blit(img, img.get_rect(center=(x0 + w / 2, cy)))


def _level_color(pct: float, over: bool = False):
    # 正常用量一律 usage_bar 珊瑚橘；轉紅使用 usage_warn（針對低對比 TN 面板微調）。
    if over or pct > 85:
        return theme.C["usage_warn"]
    return theme.C["usage_bar"]


def _draw_group(surface, x0: float, w: float, y: float, label: str,
                pct: float | None, resets_at, now: datetime, muted: bool = False,
                window_s: float | None = None) -> None:
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    pct_color = theme.C["muted"] if muted else theme.C["text"]
    _text(surface, label, 15, label_color, x0, y)
    countdown = fmt_countdown(resets_at, now)
    _text(surface, f"剩 {countdown}", 12, theme.C["muted"],
          x0 + w - 52, y + 2, "topright")
    pct_label = f"{round(pct)}%" if pct is not None else "—"
    _text(surface, pct_label, 17, pct_color, x0 + w, y - 1, "topright", bold=True)

    bar_x = x0 + BAR_MARGIN
    bar_w = w - 2 * BAR_MARGIN
    bar_y = y + BAR_Y_OFFSET
    pygame.draw.rect(surface, theme.C["card"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     border_radius=BAR_RADIUS)
    pygame.draw.rect(surface, theme.C["panel_line"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     width=1, border_radius=BAR_RADIUS)
    over = (not muted and window_s is not None
            and over_pace(pct, resets_at, now, window_s))
    if pct is not None and pct > 0:
        fill_w = max(0.0, min(bar_w, bar_w * pct / 100))
        fill_color = theme.C["muted"] if muted else _level_color(pct, over)
        pygame.draw.rect(surface, fill_color,
                         pygame.Rect(round(bar_x), round(bar_y), round(fill_w), BAR_H),
                         border_radius=BAR_RADIUS)
    if window_s is not None and not muted:
        pace = pace_pct(resets_at, now, window_s)
        if pace is not None:
            px = bar_x + bar_w * pace / 100
            pygame.draw.line(surface, theme.C["text2"],
                             (round(px), round(bar_y - 3)),
                             (round(px), round(bar_y + BAR_H + 3)), 1)


def visible_sections(usage, now: datetime, enabled_sources=None, oa_aliases=None,
                     oa_hidden=None):
    """純顯示決策：回傳仍應畫出的 ``(title, groups, age)`` 區塊。

    每個 provider 以自己的成功抓取時間判斷新鮮度。Claude 在缺少
    ``claude_fetched_at`` 時可退回全域 ``fetched_at``（兩者語意相同）。
    Antigravity / 舊單一 OpenAI 區塊 **不**退回 Claude／全域時間——舊快取缺分來源
    時間戳時以中性年齡 0 處理（不顯示「N 分前」、不誤標過期）。多帳號 OpenAI
    則依帳號自己的 ``fetched_at``，再退回 OA / 全域時間，以相容新 producer payload。
    """
    if usage is None:
        return []
    enabled = set(DEFAULT_SOURCES if enabled_sources is None else enabled_sources)

    def age_for(field, *, fallback_to_global: bool):
        fetched = getattr(usage, field, None)
        if fetched is None and fallback_to_global:
            fetched = usage.fetched_at
        if fetched is None:
            return 0.0
        return (now - fetched).total_seconds()

    def age_for_oa_account(account):
        fetched = account.fetched_at or getattr(usage, "oa_fetched_at", None) or usage.fetched_at
        return (now - fetched).total_seconds() if fetched is not None else 0.0

    aliases = oa_aliases or {}
    hidden = set(oa_hidden or ())

    def oa_title(account):
        alias = aliases.get(account.account_id, "")
        if alias:
            return f"OPENAI · {alias}"
        if account.name:
            return f"OPENAI · {account.name.upper()}"
        return "OPENAI"

    claude_groups = [
        ("5H SESSION", usage.session_pct, usage.session_resets_at,
         WINDOW_S["session"]),
        ("本週", usage.weekly_pct, usage.weekly_resets_at, WINDOW_S["weekly"]),
    ]
    if usage.fable_pct is not None:
        claude_groups.append(("FABLE", usage.fable_pct, usage.fable_resets_at,
                              WINDOW_S["fable"]))

    sections = []
    claude_age = age_for("claude_fetched_at", fallback_to_global=True)
    if "claude" in enabled and claude_age < HIDE_AFTER_S:
        sections.append(("CLAUDE CODE", claude_groups, claude_age))

    has_ag = (usage.ag_5h_pct is not None or usage.ag_weekly_pct is not None)
    ag_age = age_for("ag_fetched_at", fallback_to_global=False)
    if "antigravity" in enabled and has_ag and ag_age < HIDE_AFTER_S:
        sections.append(("ANTIGRAVITY · GEMINI", [
            ("5H", usage.ag_5h_pct, usage.ag_5h_resets_at, WINDOW_S["ag_5h"]),
            ("本週", usage.ag_weekly_pct, usage.ag_weekly_resets_at, WINDOW_S["ag_weekly"]),
        ], ag_age))

    if "openai" in enabled:
        oa_accounts = getattr(usage, "oa_accounts", ())
        if oa_accounts:
            for account in oa_accounts:
                if account.account_id in hidden:
                    continue
                oa_age = age_for_oa_account(account)
                if oa_age < HIDE_AFTER_S:
                    sections.append((oa_title(account), [
                        ("本週", account.weekly_pct, account.weekly_resets_at, WINDOW_S["oa_weekly"]),
                    ], oa_age))
        else:
            oa_age = age_for("oa_fetched_at", fallback_to_global=False)
            if usage.oa_weekly_pct is not None and oa_age < HIDE_AFTER_S:
                sections.append(("OPENAI", [
                    ("本週", usage.oa_weekly_pct, usage.oa_weekly_resets_at, WINDOW_S["oa_weekly"]),
                ], oa_age))
    return sections


def render(surface, usage, now: datetime, x0: float = 1540, w: float = 360,
           enabled_sources=None, oa_aliases=None, oa_hidden=None) -> None:
    """畫可見 usage 區塊；未勾選、沒有資料或超過一天的來源完全不留痕跡。"""
    sections = visible_sections(usage, now, enabled_sources, oa_aliases, oa_hidden)
    if not sections:
        return

    title_y = TITLE_Y
    previous_bar_bottom = None
    for i, (title, groups, age) in enumerate(sections):
        if i > 0:
            sep_y = previous_bar_bottom + SECTION_SEP_GAP
            pygame.draw.line(surface, theme.C["panel_line"],
                             (round(x0), round(sep_y)),
                             (round(x0 + w), round(sep_y)), 1)
            title_y = sep_y + SECTION_TITLE_GAP

        _text(surface, title, 14, theme.C["muted"], x0, title_y)
        if age > STALE_AFTER_S:
            _text(surface, f"({int(age // 60)} 分前)", 16, theme.C["muted"],
                  x0 + w, title_y, "topright")
        y = title_y + SECTION_FIRST_GROUP
        for label, pct, resets_at, win in groups:
            _draw_group(surface, x0, w, y, label, pct, resets_at, now,
                        muted=age > VERY_STALE_AFTER_S,
                        window_s=win)
            previous_bar_bottom = y + BAR_Y_OFFSET + BAR_H
            y += GROUP_STEP
