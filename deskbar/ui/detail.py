import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme


# 三欄版面（中欄 TL_X0=420..TL_X1=1520）：卡片必須完全落在中欄內，不能蓋到左欄
# （PANEL_W=400）也不能溢進右欄的 usage 油表；左右各留 100px，不頂邊。
CARD_X, CARD_Y, CARD_W, CARD_H = 520, 60, 900, 360
TEXT_X = CARD_X + 40            # 卡片內文字左邊距，固定 40px
TEXT_MAX_W = CARD_W - 80        # 內文可用寬度：左右各留 40px


def render(surface, event) -> list[Hit]:
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(CARD_X, CARD_Y, CARD_W, CARD_H)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
    pygame.draw.rect(surface, theme.C["panel_line"], card, 1, border_radius=10)
    f_time = "%H:%M"
    if event.all_day:
        when = f"{event.start.month}月{event.start.day}日 · 整日"
    else:
        when = f"{event.start.strftime(f_time)} – {event.end.strftime(f_time)}"
    y = CARD_Y + 40
    img = theme.font(40).render(event.title, True, theme.C["text"])
    surface.blit(img, (TEXT_X, y)); y += 64
    img = theme.font(28).render(when, True, theme.C["text2"])
    surface.blit(img, (TEXT_X, y)); y += 48
    if event.location:
        img = theme.font(24).render(f"地點：{event.location}", True, theme.C["text2"])
        surface.blit(img, (TEXT_X, y)); y += 40
    if event.description:
        lines = theme.wrap_lines(event.description, theme.font(22), TEXT_MAX_W, 2)
        for line in lines:
            img = theme.font(22).render(line, True, theme.C["muted"])
            surface.blit(img, (TEXT_X, y)); y += 28
    img = theme.font(22).render("點擊空白處關閉", True, theme.C["muted"])
    surface.blit(img, (TEXT_X, CARD_Y + 312))
    return [Hit(Rect(0, 0, 1920, 480), "close", None),
            Hit(Rect(card.x, card.y, card.w, card.h), "noop", None)]
