"""行程模式：時間排序、橫向卡片流。"""
from __future__ import annotations

from datetime import datetime

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

CARD_W = 300
CARD_GAP = 16
MAX_CARDS = 4


def render_agenda(surface, events, settings, win_start: datetime, win_end: datetime,
                  now: datetime, area: Rect) -> list[Hit]:
    hits: list[Hit] = []
    in_window = sorted(
        (e for e in events if e.end > win_start and e.start < win_end),
        key=lambda e: e.start)
    if not in_window:
        img = theme.font(26).render("接下來沒有行程", True, theme.C["muted"])
        surface.blit(img, img.get_rect(center=(area.x + area.w / 2, area.y + area.h / 2)))
        return hits

    shown = in_window[:MAX_CARDS]
    extra = len(in_window) - len(shown)
    x = area.x
    for e in shown:
        acc = settings.accounts.get(e.account)
        main, _dark = theme.account_color(acc.color if acc else 0)
        card = pygame.Rect(int(x), int(area.y), CARD_W - CARD_GAP, int(area.h))
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
        pygame.draw.rect(surface, main, pygame.Rect(card.x, card.y, 5, card.height),
                         border_radius=3)
        d0, d1 = now.date(), e.start.date()
        if d1 == d0:
            prefix = ""
        elif (d1 - d0).days == 1:
            prefix = "明天 "
        else:
            prefix = f"{d1.month}/{d1.day} "
        when = prefix + ("整日" if e.all_day
                         else f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}")
        img = theme.font(20).render(when, True, theme.C["muted"])
        surface.blit(img, (card.x + 20, card.y + 20))
        title_lines = theme.wrap_lines(e.title, theme.font(26), card.width - 40, 2)
        ty = card.y + 56
        for line in title_lines:
            img = theme.font(26).render(line, True, theme.C["text"])
            surface.blit(img, (card.x + 20, ty))
            ty += 32
        hits.append(Hit(Rect(card.x, card.y, card.width, card.height), "open_detail", e))
        x += CARD_W

    if extra > 0:
        label = f"＋{extra}"
        img = theme.font(24).render(label, True, theme.C["muted"])
        pill = pygame.Rect(0, 0, img.get_width() + 24, img.get_height() + 16)
        pill.center = (int(x + 10 + pill.width / 2), int(area.y + area.h / 2))
        # 「膠囊」樣式跟「＋N 整日」一致：theme.C["card"] 底＋panel_line 邊框。
        pygame.draw.rect(surface, theme.C["card"], pill, border_radius=pill.height // 2)
        pygame.draw.rect(surface, theme.C["panel_line"], pill, 1, border_radius=pill.height // 2)
        surface.blit(img, img.get_rect(center=pill.center))
    return hits
