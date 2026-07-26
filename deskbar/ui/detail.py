import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme


# 卡片必須完全落在時間軸區（x=500 起）內，不能蓋到左面板（PANEL_W=480）；
# 右緣 1800 在時間軸右界 1900 內留白，不頂邊。
CARD_X, CARD_Y, CARD_W, CARD_H = 560, 60, 1240, 360
TEXT_X = CARD_X + 40            # 卡片內文字左邊距，固定 40px
TEXT_MAX_W = CARD_W - 80        # 內文可用寬度：左右各留 40px


def render(surface, event) -> list[Hit]:
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(CARD_X, CARD_Y, CARD_W, CARD_H)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
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


MAX_ALLDAY_LIST_LINES = 8   # 超過就收成「…以及其他 N 筆」，避免蓋過下方關閉提示

# 同樣要完全落在時間軸區（x=500 起）內，不蓋左面板；右緣 1760 留在 1900 內。
ALLDAY_CARD_X, ALLDAY_CARD_Y, ALLDAY_CARD_W, ALLDAY_CARD_H = 560, 40, 1200, 400
ALLDAY_TEXT_X = ALLDAY_CARD_X + 40


def render_allday_list(surface, events) -> list[Hit]:
    """整日 chips 排不下時的「＋N 整日」點開浮層：沿用 render() 同一套全螢幕
    半透明遮罩＋卡片樣式，簡單列出全部整日事件的日期＋標題，點外側關閉
    （noop/close 機制與 render() 完全共用）。"""
    overlay = pygame.Surface((1920, 480), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))
    card = pygame.Rect(ALLDAY_CARD_X, ALLDAY_CARD_Y, ALLDAY_CARD_W, ALLDAY_CARD_H)
    pygame.draw.rect(surface, theme.C["card"], card, border_radius=10)
    img = theme.font(32).render(f"整日行程（{len(events)}）", True, theme.C["text"])
    surface.blit(img, (ALLDAY_TEXT_X, ALLDAY_CARD_Y + 20))
    y = ALLDAY_CARD_Y + 76
    shown = events[:MAX_ALLDAY_LIST_LINES]
    for e in shown:
        line = f"{e.start.month}/{e.start.day} · {e.title}"
        img = theme.font(24).render(line[:60], True, theme.C["text2"])
        surface.blit(img, (ALLDAY_TEXT_X, y))
        y += 32
    extra = len(events) - len(shown)
    if extra > 0:
        img = theme.font(22).render(f"…以及其他 {extra} 筆", True, theme.C["muted"])
        surface.blit(img, (ALLDAY_TEXT_X, y))
    img = theme.font(22).render("點擊空白處關閉", True, theme.C["muted"])
    surface.blit(img, (ALLDAY_TEXT_X, ALLDAY_CARD_Y + 370))
    return [Hit(Rect(0, 0, 1920, 480), "close", None),
            Hit(Rect(card.x, card.y, card.w, card.h), "noop", None)]
