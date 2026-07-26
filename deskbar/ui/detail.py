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


MAX_ALLDAY_LIST_LINES = 8   # 超過就收成「…以及其他 N 筆」，避免蓋過下方關閉提示


def render_allday_list(surface, events) -> list[Hit]:
    """整日 chips 排不下時的「＋N 整日」點開浮層：沿用 render() 同一套全螢幕
    半透明遮罩＋卡片樣式，簡單列出全部整日事件的日期＋標題，點外側關閉
    （noop/close 機制與 render() 完全共用）。"""
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(360, 40, 1200, 400)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
    img = theme.font(32).render(f"整日行程（{len(events)}）", True, theme.C["text"])
    surface.blit(img, (400, 60))
    y = 116
    shown = events[:MAX_ALLDAY_LIST_LINES]
    for e in shown:
        line = f"{e.start.month}/{e.start.day} · {e.title}"
        img = theme.font(24).render(line[:60], True, theme.C["text2"])
        surface.blit(img, (400, y))
        y += 32
    extra = len(events) - len(shown)
    if extra > 0:
        img = theme.font(22).render(f"…以及其他 {extra} 筆", True, theme.C["muted"])
        surface.blit(img, (400, y))
    img = theme.font(22).render("點擊空白處關閉", True, theme.C["muted"])
    surface.blit(img, (400, 410))
    return [Hit(Rect(0, 0, 1920, 480), "close", None),
            Hit(Rect(card.x, card.y, card.w, card.h), "noop", None)]
