"""右欄：Claude Code、Antigravity (Gemini) 與 OpenAI usage 油表。

全寬單欄、由上到下三區：
1. CLAUDE CODE 區：5H SESSION / 本週 / FABLE（FABLE 無資料時略過）
2. ANTIGRAVITY · GEMINI 區：5H / 本週（無資料時整區略過，不畫分隔線與標題）
3. OPENAI 區：每個帳號一區（無資料時整區略過，不畫分隔線與標題）
4. CURSOR 區：本期（帳單週期約一個月；無資料時整區略過）
5. OPENCODE GO 區：5H / 本週（無資料時整區略過）

2026-09-11 起來源多到一欄放不下（6 區 10 列）：render() 會先算總高度，超過可用高度時
把垂直間距等比例縮小（只縮間距，不縮字級、不縮長條），縮到底線仍放不下才裁掉最後幾區。

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
# 2026-09-10：所有來源的刷新間隔都是 300 秒，門檻也放 300 會讓每一區在下次刷新前
# 一律掛上「(5 分前)」——變成常駐雜訊而不是警訊。放到 900 秒＝連續漏三輪才提醒。
STALE_AFTER_S = 900       # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」
VERY_STALE_AFTER_S = 3600 # 超過這麼久，整組轉 muted 灰（agent 可能已經停了）
HIDE_AFTER_S = 24 * 60 * 60
DEFAULT_SOURCES = ("claude", "antigravity", "openai", "cursor", "opencode")


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _center_text(surface, s, size, color, x0, w, cy):
    img = theme.text_surface(s, size, color)
    surface.blit(img, img.get_rect(center=(x0 + w / 2, cy)))


def is_exhausted(pct) -> bool:
    """額度用完＝這個來源現在不能用。>=100 就算，浮點誤差不必特別容忍。"""
    if pct is None or isinstance(pct, bool):
        return False
    try:
        return float(pct) >= 100
    except (TypeError, ValueError):
        return False


def _level_color(pct: float, over: bool = False):
    # 正常用量一律 usage_bar 珊瑚橘；快用完 usage_warn 橘紅；
    # 用完（>=100%）走 usage_full 純紅——那代表現在根本不能用，要一眼看得出差別。
    if is_exhausted(pct):
        return theme.C["usage_full"]
    if over or pct > 85:
        return theme.C["usage_warn"]
    return theme.C["usage_bar"]


def _draw_group(surface, x0: float, w: float, y: float, label: str,
                pct: float | None, resets_at, now: datetime, muted: bool = False,
                window_s: float | None = None) -> None:
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    if muted:
        pct_color = theme.C["muted"]
    elif is_exhausted(pct):
        pct_color = theme.C["usage_full"]
    else:
        pct_color = theme.C["text"]
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

    if "cursor" in enabled:
        cu_age = age_for("cu_fetched_at", fallback_to_global=False)
        cu_pct = getattr(usage, "cu_pct", None)
        if cu_pct is not None and cu_age < HIDE_AFTER_S:
            # Cursor 的視窗是帳單週期（約一個月），不是一週——標籤用「本期」。
            sections.append(("CURSOR", [
                ("本期", cu_pct, getattr(usage, "cu_resets_at", None), WINDOW_S["cu"]),
            ], cu_age))

    if "opencode" in enabled:
        og_age = age_for("og_fetched_at", fallback_to_global=False)
        og_5h = getattr(usage, "og_5h_pct", None)
        og_weekly = getattr(usage, "og_weekly_pct", None)
        if (og_5h is not None or og_weekly is not None) and og_age < HIDE_AFTER_S:
            sections.append(("OPENCODE GO", [
                ("5H", og_5h, getattr(usage, "og_5h_resets_at", None), WINDOW_S["og_5h"]),
                ("本週", og_weekly, getattr(usage, "og_weekly_resets_at", None), WINDOW_S["og_weekly"]),
            ], og_age))
    return sections


MIN_GROUP_STEP = 32       # 壓縮下限：字列 17px＋橫條 9px＋餘裕，再低會貼在一起
MIN_SECTION_GAP = 10      # sep_gap + title_gap 合計的下限
DEFAULT_HEIGHT = 480 - 6  # 右欄可用高度（螢幕 480，底下留一點邊）


def layout_height(group_counts, *, group_step=GROUP_STEP, sep_gap=SECTION_SEP_GAP,
                  title_gap=SECTION_TITLE_GAP, first_group=SECTION_FIRST_GROUP) -> float:
    """純函數：這組區塊照給定間距畫完，最後一條橫條的底在哪個 y。"""
    if not group_counts:
        return 0.0
    y = TITLE_Y
    bottom = 0.0
    for i, n in enumerate(group_counts):
        if i > 0:
            y = bottom + sep_gap + title_gap
        bottom = y + first_group + (n - 1) * group_step + BAR_Y_OFFSET + BAR_H
    return bottom


def fit_layout(group_counts, height: float = DEFAULT_HEIGHT) -> dict:
    """純函數：放得下就用預設間距；放不下就等比例縮間距（不縮字級／橫條），
    縮到下限還放不下就回 max_sections 讓呼叫端裁掉最後幾區。"""
    default = {"group_step": GROUP_STEP, "sep_gap": SECTION_SEP_GAP,
               "title_gap": SECTION_TITLE_GAP, "first_group": SECTION_FIRST_GROUP,
               "max_sections": len(group_counts), "compact": False}
    if layout_height(group_counts) <= height:
        return default
    # 二分搜尋一個 0..1 的縮放係數，套在三個「可伸縮」的間距上。
    def scaled(k):
        return {
            "group_step": max(MIN_GROUP_STEP, round(GROUP_STEP * k)),
            "sep_gap": max(MIN_SECTION_GAP // 2, round(SECTION_SEP_GAP * k)),
            "title_gap": max(MIN_SECTION_GAP - MIN_SECTION_GAP // 2, round(SECTION_TITLE_GAP * k)),
            "first_group": max(18, round(SECTION_FIRST_GROUP * k)),
        }
    lo, hi = 0.0, 1.0
    best = scaled(0.0)
    for _ in range(12):
        mid = (lo + hi) / 2
        cand = scaled(mid)
        if layout_height(group_counts, **cand) <= height:
            best, lo = cand, mid
        else:
            hi = mid
    if layout_height(group_counts, **best) <= height:
        return {**best, "max_sections": len(group_counts), "compact": True}
    # 連最緊也放不下：從尾端裁區塊
    for keep in range(len(group_counts) - 1, 0, -1):
        if layout_height(group_counts[:keep], **best) <= height:
            return {**best, "max_sections": keep, "compact": True}
    return {**best, "max_sections": 1, "compact": True}


def render(surface, usage, now: datetime, x0: float = 1540, w: float = 360,
           enabled_sources=None, oa_aliases=None, oa_hidden=None,
           height: float = DEFAULT_HEIGHT) -> None:
    """畫可見 usage 區塊；未勾選、沒有資料或超過一天的來源完全不留痕跡。
    放不下時自動縮間距（見 fit_layout）。"""
    sections = visible_sections(usage, now, enabled_sources, oa_aliases, oa_hidden)
    if not sections:
        return

    layout = fit_layout([len(groups) for _t, groups, _a in sections], height)
    sections = sections[:layout["max_sections"]]

    title_y = TITLE_Y
    previous_bar_bottom = None
    for i, (title, groups, age) in enumerate(sections):
        if i > 0:
            sep_y = previous_bar_bottom + layout["sep_gap"]
            pygame.draw.line(surface, theme.C["panel_line"],
                             (round(x0), round(sep_y)),
                             (round(x0 + w), round(sep_y)), 1)
            title_y = sep_y + layout["title_gap"]

        _text(surface, title, 14, theme.C["muted"], x0, title_y)
        if age > STALE_AFTER_S:
            _text(surface, f"({int(age // 60)} 分前)", 16, theme.C["muted"],
                  x0 + w, title_y, "topright")
        y = title_y + layout["first_group"]
        for label, pct, resets_at, win in groups:
            _draw_group(surface, x0, w, y, label, pct, resets_at, now,
                        muted=age > VERY_STALE_AFTER_S,
                        window_s=win)
            previous_bar_bottom = y + BAR_Y_OFFSET + BAR_H
            y += layout["group_step"]
