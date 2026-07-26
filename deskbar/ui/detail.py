import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme


def render(surface, event) -> list[Hit]:
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(360, 60, 1200, 360)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
    f_time = "%H:%M"
    if event.all_day:
        when = f"{event.start.month}月{event.start.day}日 · 整日"
    else:
        when = f"{event.start.strftime(f_time)} – {event.end.strftime(f_time)}"
    y = 100
    img = theme.font(40).render(event.title, True, theme.C["text"])
    surface.blit(img, (400, y)); y += 64
    img = theme.font(28).render(when, True, theme.C["text2"])
    surface.blit(img, (400, y)); y += 48
    if event.location:
        img = theme.font(24).render(f"地點：{event.location}", True, theme.C["text2"])
        surface.blit(img, (400, y)); y += 40
    if event.description:
        desc = event.description.replace("\n", " ")[:80]
        img = theme.font(22).render(desc, True, theme.C["muted"])
        surface.blit(img, (400, y))
    img = theme.font(22).render("點擊空白處關閉", True, theme.C["muted"])
    surface.blit(img, (400, 372))
    return [Hit(Rect(0, 0, 1920, 480), "close", None),
            Hit(Rect(card.x, card.y, card.w, card.h), "noop", None)]
