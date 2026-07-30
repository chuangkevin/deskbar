"""「螢幕」設定頁：上下班時間、日/夜亮度、深夜熄屏時段、旋轉。

下班時間一到自動套用下班亮度（軟體疊黑，見 deskbar.brightness 檔頭）；
睡眠時段內螢幕全黑、觸摸喚醒 30 秒。亮度改動即時生效（下一幀 flip 就套），
方便邊調邊看。版面：3×2 六張調整卡＋底部一列（睡眠開關/旋轉/目前亮度）。
"""
from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

# (欄位, 標題, 單位/格式, 步進, 下限, 上限)
FIELDS = [
    ("work_start_min", "上班開始", "min", 30, 0, 1410),
    ("work_end_min", "下班時間", "min", 30, 0, 1410),
    ("brightness_day", "上班亮度", "pct", 10, 10, 100),
    ("brightness_night", "下班亮度", "pct", 10, 10, 100),
    ("sleep_start_min", "睡眠開始", "min", 30, 0, 1410),
    ("sleep_end_min", "睡眠結束", "min", 30, 0, 1410),
]
_CARD_W, _CARD_H = 600, 148
_ROW_Y = (84, 244)
_COL_X = (40, 660, 1280)


def _text_bold(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size, bold=True).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _btn(surface, label, rect, action, data, hits, size=26):
    pygame.draw.rect(surface, theme.C["card"], rect, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], rect, 1, border_radius=8)
    img = theme.font(size).render(label, True, theme.C["text"])
    surface.blit(img, img.get_rect(center=rect.center))
    hits.append(Hit(Rect(rect.x, rect.y, rect.w, rect.h), action, data))


def render(surface, settings) -> list:
    hits: list = []
    _text_bold(surface, "螢幕", 32, theme.C["text"], 40, 20)
    _text(surface, "下班自動降亮度；睡眠時段熄屏、觸摸喚醒 30 秒", 22,
          theme.C["muted"], 180, 30)
    _btn(surface, "返回", pygame.Rect(1700, 16, 180, 52), "open_settings", None, hits,
         size=24)

    sleep_dimmed = not getattr(settings, "sleep_enabled", False)
    for i, (field, title, fmt, step, lo, hi) in enumerate(FIELDS):
        x, y = _COL_X[i % 3], _ROW_Y[i // 3]
        card = pygame.Rect(x, y, _CARD_W, _CARD_H)
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
        pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=10)
        muted_card = field.startswith("sleep_") and sleep_dimmed
        _text(surface, title + ("（未啟用）" if muted_card else ""), 22,
              theme.C["muted"] if muted_card else theme.C["text2"], x + 24, y + 14)
        val = getattr(settings, field)
        label = f"{val // 60:02d}:{val % 60:02d}" if fmt == "min" else f"{val}%"
        _text(surface, label, 40,
              theme.C["muted"] if muted_card else theme.C["text"],
              x + _CARD_W / 2, y + 66, "center")
        _btn(surface, "−", pygame.Rect(x + 20, y + _CARD_H - 60, 150, 48),
             "scr_adj", (field, -step, lo, hi), hits, size=30)
        _btn(surface, "＋", pygame.Rect(x + _CARD_W - 170, y + _CARD_H - 60, 150, 48),
             "scr_adj", (field, step, lo, hi), hits, size=30)

    on = getattr(settings, "sleep_enabled", False)
    _btn(surface, f"睡眠熄屏：{'開' if on else '關'}",
         pygame.Rect(40, 408, 340, 56), "toggle_sleep", None, hits, size=24)
    _btn(surface, "旋轉螢幕 180°", pygame.Rect(400, 408, 300, 56), "rotate", None,
         hits, size=24)
    from deskbar import brightness
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    cur = brightness.effective(settings, now.hour * 60 + now.minute, awake=True)
    _text(surface, f"目前套用亮度：{cur}%", 22, theme.C["muted"], 740, 424)
    return hits
