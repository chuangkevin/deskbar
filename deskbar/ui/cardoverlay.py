"""待辦卡詳情浮層：點卡放大看全文。

2×4 卡牆每格只有 ~540×90px，標題常被截斷——點卡彈出中央大卡顯示完整
標題（最多 4 行）、狀態、專案、到期與優先度。modal 語意：開著時 hits
只剩全畫面一顆「點任意處關閉」，滑動手勢也一律當關閉（app 端保證）。
"""
from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.linear import state_rgb
from deskbar.ui import Hit
from deskbar.ui import theme

_PRIO = {1: "緊急", 2: "高", 3: "中", 4: "低"}


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def render(surface, issue, now) -> list:
    sw, sh = surface.get_width(), surface.get_height()
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 165))
    surface.blit(dim, (0, 0))

    w, h = 980, 360
    x, y = (sw - w) // 2, (sh - h) // 2
    card = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=16)
    pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=16)
    main = theme.col(state_rgb(issue.state_color))
    pygame.draw.rect(surface, main, pygame.Rect(x + 8, y + 8, 5, h - 16),
                     border_radius=3)

    tx = x + 40
    r = _text(surface, issue.identifier, 20, theme.C["muted"], tx, y + 26)
    _text(surface, issue.state_name, 20, main, r.right + 14, y + 26, bold=True)
    right_x = x + w - 32
    if issue.due is not None:
        d = (issue.due - now.date()).days
        if d < 0:
            label, col = f"逾期 {-d} 天", theme.C["warn"]
        elif d == 0:
            label, col = "今天到期", theme.C["warn"]
        else:
            label, col = f"{issue.due.month}/{issue.due.day} 到期", theme.C["muted"]
        rr = _text(surface, label, 20, col, right_x, y + 26, "topright", bold=d <= 0)
        right_x = rr.left - 20
    prio = _PRIO.get(issue.priority)
    if prio:
        _text(surface, f"優先度 {prio}", 20,
              theme.C["warn"] if issue.priority == 1 else theme.C["muted"],
              right_x, y + 26, "topright")

    font = theme.font(30, weight="medium")
    yy = y + 76
    for line in theme.wrap_lines(issue.title, font, w - 80, 4):
        surface.blit(theme.text_surface(line, 30, theme.C["text"],
                                        weight="medium"), (tx, yy))
        yy += 44
    if issue.project:
        _text(surface, issue.project, 20, theme.C["muted"], tx, y + h - 48)
    _text(surface, "點任意處關閉", 18, theme.C["muted"], x + w - 32, y + h - 46,
          "topright")
    return [Hit(Rect(0, 0, sw, sh), "overlay_close", None)]
