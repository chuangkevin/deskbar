import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import dashboard, theme


# 三欄版面（中欄 TL_X0..TL_X1，見 dashboard 常數）：卡片必須完全落在中欄內，
# 不能蓋到左欄（PANEL_W）也不能溢進右欄的 usage 油表；左右各留 100px，不頂邊。
# CARD 幾何每次用時從 dashboard.TL_X1 現算（usage_width 可調中欄右界，import 時
# 算死會在調寬後錯位）。
CARD_Y, CARD_H = 60, 360


def _card_geom():
    card_x = dashboard.TL_X0 + 100
    card_w = dashboard.TL_X1 - dashboard.TL_X0 - 200
    text_x = card_x + 40
    return card_x, card_w, text_x, card_w - 80


# 相容舊參照（測試／外部 import）：模組常數保留，但 render 一律用 _card_geom() 現算。
CARD_X = dashboard.TL_X0 + 100
CARD_W = dashboard.TL_X1 - dashboard.TL_X0 - 200
TEXT_X = CARD_X + 40            # 卡片內文字左邊距，固定 40px
TEXT_MAX_W = CARD_W - 80        # 內文可用寬度：左右各留 40px


def render(surface, event) -> list[Hit]:
    card_x, card_w, text_x, text_max_w = _card_geom()
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(card_x, CARD_Y, card_w, CARD_H)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
    pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=10)
    f_time = "%H:%M"
    if event.all_day:
        when = f"{event.start.month}月{event.start.day}日 · 整日"
    else:
        when = f"{event.start.strftime(f_time)} – {event.end.strftime(f_time)}"
    y = CARD_Y + 40
    img = theme.text_surface(event.title, 40, theme.C["text"])
    surface.blit(img, (text_x, y)); y += 64
    img = theme.text_surface(when, 28, theme.C["text2"])
    surface.blit(img, (text_x, y)); y += 48
    if event.location:
        img = theme.text_surface(f"地點：{event.location}", 24, theme.C["text2"])
        surface.blit(img, (text_x, y)); y += 40
    if event.description:
        lines = theme.wrap_lines(event.description, theme.font(22), text_max_w, 2)
        for line in lines:
            img = theme.text_surface(line, 22, theme.C["muted"])
            surface.blit(img, (text_x, y)); y += 28
    img = theme.text_surface("點擊空白處關閉", 22, theme.C["muted"])
    surface.blit(img, (text_x, CARD_Y + 312))
    return [Hit(Rect(0, 0, 1920, 480), "close", None),
            Hit(Rect(card.x, card.y, card.w, card.h), "noop", None)]
