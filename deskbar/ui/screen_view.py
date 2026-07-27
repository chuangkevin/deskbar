"""「螢幕」設定頁：上下班時間、日/夜亮度、旋轉。

下班時間一到自動套用下班亮度（軟體疊黑，見 deskbar.brightness 檔頭）；
亮度改動即時生效（下一幀 flip 就套），方便邊調邊看。旋轉鈕從主設定頁
搬過來——它本來就屬於螢幕範疇，也還主設定頁一排乾淨的控制列。
"""
from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

# (欄位, 標題, 單位/格式, 步進, 下限, 上限)
FIELDS = [
    ("work_start_hour", "上班開始", "hour", 1, 0, 23),
    ("work_end_hour", "下班時間", "hour", 1, 0, 23),
    ("brightness_day", "上班亮度", "pct", 10, 10, 100),
    ("brightness_night", "下班亮度", "pct", 10, 10, 100),
]
_CARD_W, _CARD_H, _CARD_Y = 430, 220, 96


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
    _text(surface, "螢幕", 32, theme.C["text"], 40, 24)
    _text(surface, "下班時間起自動套用下班亮度", 22, theme.C["muted"], 200, 34)
    _btn(surface, "返回", pygame.Rect(1700, 20, 180, 52), "open_settings", None, hits,
         size=24)

    for i, (field, title, fmt, step, lo, hi) in enumerate(FIELDS):
        x = 40 + i * 460
        card = pygame.Rect(x, _CARD_Y, _CARD_W, _CARD_H)
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
        pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=10)
        _text(surface, title, 24, theme.C["text2"], x + 24, _CARD_Y + 18)
        val = getattr(settings, field)
        label = f"{val:02d}:00" if fmt == "hour" else f"{val}%"
        _text(surface, label, 44, theme.C["text"], x + _CARD_W / 2, _CARD_Y + 92,
              "center")
        _btn(surface, "−", pygame.Rect(x + 24, _CARD_Y + 136, 150, 64),
             "scr_adj", (field, -step, lo, hi), hits, size=34)
        _btn(surface, "＋", pygame.Rect(x + _CARD_W - 174, _CARD_Y + 136, 150, 64),
             "scr_adj", (field, step, lo, hi), hits, size=34)

    _btn(surface, "旋轉螢幕 180°", pygame.Rect(40, 360, 300, 64), "rotate", None,
         hits, size=24)
    from deskbar import brightness
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_h = datetime.now(ZoneInfo("Asia/Taipei")).hour
    cur = brightness.effective(settings, now_h)
    _text(surface, f"目前套用亮度：{cur}%", 22, theme.C["muted"], 380, 380)
    return hits
