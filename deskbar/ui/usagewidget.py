"""右欄：Claude Code usage 油表——三組（5H SESSION／本週／FABLE）橫條，唯讀顯示，
不產生任何 Hit（純資訊面板，跟左欄時鐘/天氣一樣不可互動）。

usage 資料完全被動：Mac 上的 agent 每 60 秒讀本機 Keychain 的 Claude Code 憑證、
打 usage API，主動 POST 到 deskbar 的 /api/usage（見 deskbar.webserver）；deskbar
本身不持有任何憑證、不主動抓取（見 deskbar.claudeusage 檔頭說明）。

兩種狀態：
- usage is None：從沒收過推送（agent 沒在跑，或還沒送過第一筆）
  → 中央提示「usage 未推送」＋「Mac agent 未執行」。
- 其餘：畫三組（FABLE 沒有資料就整組略過，見上游 payload）。距上次推送
  （fetched_at）超過 STALE_AFTER_S 秒，標題旁加「(N 分前)」；超過
  VERY_STALE_AFTER_S 秒（代表 agent 可能已經停了很久），三組全部轉 muted 灰，
  跟正常新鮮資料的分級色一眼區分開。
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
STALE_AFTER_S = 300          # fetched_at 超過這麼久沒更新，標題旁加「(N 分前)」
VERY_STALE_AFTER_S = 3600    # 超過這麼久，整組轉 muted 灰（agent 可能已經停了）

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
                pct: float | None, resets_at, now: datetime, muted: bool = False) -> None:
    label_color = theme.C["muted"] if muted else theme.C["text2"]
    pct_color = theme.C["muted"] if muted else theme.C["text"]
    _text(surface, label, 18, label_color, x0, y)
    pct_label = f"{round(pct)}%" if pct is not None else "—"
    _text(surface, pct_label, 20, pct_color, x0 + w - 8, y - 2, "topright")

    bar_x = x0 + BAR_MARGIN
    bar_w = w - 2 * BAR_MARGIN
    bar_y = y + 26
    pygame.draw.rect(surface, theme.C["card"],
                     pygame.Rect(round(bar_x), round(bar_y), round(bar_w), BAR_H),
                     border_radius=BAR_RADIUS)
    if pct is not None and pct > 0:
        fill_w = max(0.0, min(bar_w, bar_w * pct / 100))
        fill_color = theme.C["muted"] if muted else _level_color(pct)
        pygame.draw.rect(surface, fill_color,
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
        _center_text(surface, "usage 未推送", 22, theme.C["muted"], x0, w, 220)
        _center_text(surface, "Mac agent 未執行", 16, theme.C["muted"], x0, w, 250)
        return

    age = (now - usage.fetched_at).total_seconds()
    muted = age > VERY_STALE_AFTER_S
    if age > STALE_AFTER_S:
        mins = int(age // 60)
        _text(surface, f"({mins} 分前)", 16, theme.C["muted"], x0 + w - 8, TITLE_Y, "topright")

    groups = [
        ("5H SESSION", usage.session_pct, usage.session_resets_at),
        ("本週", usage.weekly_pct, usage.weekly_resets_at),
    ]
    if usage.fable_pct is not None:
        groups.append(("FABLE", usage.fable_pct, usage.fable_resets_at))

    y = GROUP_START_Y
    for label, pct, resets_at in groups:
        _draw_group(surface, x0, w, y, label, pct, resets_at, now, muted=muted)
        y += GROUP_STEP
