import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme


def render(surface, alarm, now) -> list[Hit]:
    flash = int(now.timestamp() * 2) % 2 == 0
    bg = theme.C["now"] if flash else theme.C["bg"]
    fg = theme.C["now_text"] if flash else theme.C["text"]
    surface.fill(bg)
    img = theme.text_surface(alarm.label, 96, fg)
    surface.blit(img, img.get_rect(center=(960, 190)))
    img = theme.text_surface(alarm.time, 48, fg)
    surface.blit(img, img.get_rect(center=(960, 300)))
    img = theme.text_surface("點擊任意處關閉", 26, fg)
    surface.blit(img, img.get_rect(center=(960, 400)))
    return [Hit(Rect(0, 0, 1920, 480), "dismiss_alarm", alarm.id)]
