"""右欄：Claude Code usage 油表——三組（5H SESSION／本週／FABLE）橫條，唯讀顯示，
不產生任何 Hit（純資訊面板，跟左欄時鐘/天氣一樣不可互動）。

三種狀態：
- usage is None：從沒連結過（或憑證檔不存在、start_usage_thread 沒啟動）
  → 中央提示「usage 未連結」＋「在 Pi 執行 make claude-login」。
- usage.needs_login：曾經連結過，但 token 已失效（refresh_token 被撤銷／4xx）
  → 中央提示「需重新登入」（warn 色）。
- 其餘：畫三組（FABLE 沒有資料就整組略過，見 deskbar.claudeusage.fetch_usage）。
"""
from __future__ import annotations

from datetime import datetime

import pygame

from deskbar.claudeusage import fmt_countdown
from deskbar.ui import theme

TITLE_Y = 60
GROUP_START_Y = 100
GROUP_STEP = 84
BAR_H = 12
BAR_RADIUS = 6
BAR_MARGIN = 20              # 橫條左右各留白，寬度＝欄寬-2*BAR_MARGIN，置中排列
STALE_AFTER_S = 180          # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」

_LOW_COLOR = (93, 202, 165)      # <60%
_MID_COLOR = (239, 169, 72)      # 60~85%
                                  # >85% 用 theme.C["warn"]


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _center_text(surface, s, size, color, x0, w, cy):
    img = theme.font(size).render(s, True, color)
    surface.blit(img, img.get_rect(center=(x0 + w / 2, cy)))


def _level_color(pct: float):
    if pct < 60:
        return theme.col(_LOW_COLOR)
    if pct <= 85:
        return theme.col(_MID_COLOR)
    return theme.C["warn"]


def _draw_group(surface, x0: float, w: float, y: float, label: str,
                pct: float | None, resets_at, now: datetime) -> None:
    _text(surface, label, 18, theme.C["text2"], x0, y)
    pct_label = f"{round(pct)}%" if pct is not None else "—"
    _text(surface, pct_label, 20, theme.C["text"], x0 + w - 8, y - 2, "topright")

    bar_x = x0 + BAR_MARGIN
    bar_w = w - 2 * BAR_MARGIN
    bar_y = y + 26
    pygame.draw.rect(surface, theme.C["card"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     border_radius=BAR_RADIUS)
    if pct is not None and pct > 0:
        fill_w = max(0.0, min(bar_w, bar_w * pct / 100))
        pygame.draw.rect(surface, _level_color(pct),
                         pygame.Rect(round(bar_x), round(bar_y), round(fill_w), BAR_H),
                         border_radius=BAR_RADIUS)

    # 不用「↻」之類的符號字形當前綴——比照 deskbar.ui.icons 的教訓（字型檔不一定
    # 內建該字符，會畫成方塊），純文字「剩 …」在任何字型下都穩定可讀。
    countdown = fmt_countdown(resets_at, now)
    _text(surface, f"剩 {countdown}", 16, theme.C["muted"], x0, bar_y + BAR_H + 8)


def render(surface, usage, now: datetime, x0: float = 1540, w: float = 360) -> None:
    """usage：deskbar.claudeusage.UsageInfo｜None（來自 Snapshot.usage）。
    x0/w 由呼叫端（dashboard.py）帶入模組常量 USAGE_X0/USAGE_W，這裡的預設值
    只是給獨立測試/工具方便，不代表版面權威定義。"""
    _text(surface, "CLAUDE CODE", 16, theme.C["muted"], x0, TITLE_Y)

    if usage is None:
        _center_text(surface, "usage 未連結", 22, theme.C["muted"], x0, w, 220)
        _center_text(surface, "在 Pi 執行 make claude-login", 16, theme.C["muted"], x0, w, 250)
        return

    age = (now - usage.fetched_at).total_seconds()
    if age > STALE_AFTER_S:
        mins = int(age // 60)
        _text(surface, f"({mins} 分前)", 16, theme.C["muted"], x0 + w - 8, TITLE_Y, "topright")

    if usage.needs_login:
        _center_text(surface, "需重新登入", 22, theme.C["warn"], x0, w, 220)
        return

    groups = [
        ("5H SESSION", usage.session_pct, usage.session_resets_at),
        ("本週", usage.weekly_pct, usage.weekly_resets_at),
    ]
    if usage.fable_pct is not None:
        groups.append(("FABLE", usage.fable_pct, usage.fable_resets_at))

    y = GROUP_START_Y
    for label, pct, resets_at in groups:
        _draw_group(surface, x0, w, y, label, pct, resets_at, now)
        y += GROUP_STEP
