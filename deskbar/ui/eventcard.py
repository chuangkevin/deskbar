"""Apple 行事曆式事件卡——中欄所有視圖共用的事件視覺語言（2026-07-28 改版）。

舊畫法（深色滿版底＋飽和彩色標題字）被 UAT 打槍「像肥宅工程師的作品」。
改採 iOS 行事曆的事件卡語彙：
- 左側 4px 圓頭帳號色條（唯一的飽和色）
- 同色「極淡底」＋ 1px 同色淡框（tint 用朝背景 lerp 的實色——事件卡本來就
  該遮住格線，iOS 同款行為，所以不需要真 alpha，Pi 上也零成本）
- 標題一律近白/近黑的內文色（不再用飽和彩字），時間字小一號、muted
- 圓角 8，卡高夠時雙行（標題＋時間），不夠就單行

帳號的「識別」由色條與淡底承擔，可讀性由中性文字承擔——兩件事分開做，
畫面就安靜下來了。
"""
from __future__ import annotations

import pygame

from deskbar.ui import theme

RADIUS = 8
ACCENT_W = 4
PAD_X = 14                   # 文字起點＝色條右側留白
TWO_LINE_MIN_H = 56          # 卡高達此值才畫第二行時間字


def tint(main, alpha: int):
    """帳號色朝主題背景 lerp——淡底/淡框的廉價假透明（平坦遮蓋語意）。"""
    a = max(0, min(255, alpha)) / 255.0
    bg = theme.C["bg"]
    return tuple(round(bg[i] + (main[i] - bg[i]) * a) for i in range(3))


def fill_color(main):
    # 淺色主題底是米白，同 lerp 比例會太搶，砍淡一點
    return tint(main, 40 if theme.current_theme() == "dark" else 34)


def border_color(main):
    return tint(main, 116 if theme.current_theme() == "dark" else 96)


def draw_card(surface, rect: "pygame.Rect", main, title: str,
              time_text: "str | None" = None, pulse_color=None,
              title_size: int = 22) -> None:
    """rect 為卡的外框（呼叫端自留卡間距）。pulse_color 非 None 時畫迫近
    脈動外框（取代淡框）。只畫，不管 hits。

    窄卡退化規則（30 分鐘行程在日視圖只有 ~45px 寬）：
    - w < 64：只畫淡底＋框（純「此時段有事」的色塊），色條/文字都不畫——
      色條會變成一根孤立的螢光棒，比沒有更醜。
    - 時間字只在「放得下完整字串」時畫；截半的「11:00 – ⋯」是廢資訊。"""
    if rect.w < 8 or rect.h < 10:
        return
    pygame.draw.rect(surface, fill_color(main), rect, border_radius=RADIUS)
    pygame.draw.rect(surface, pulse_color or border_color(main), rect,
                     width=2 if pulse_color else 1, border_radius=RADIUS)
    if rect.w < 64:
        return
    bar = pygame.Rect(rect.x + 4, rect.y + 4, ACCENT_W, max(2, rect.h - 8))
    pygame.draw.rect(surface, main, bar, border_radius=ACCENT_W // 2)

    text_x = rect.x + 4 + ACCENT_W + 8
    max_w = rect.w - (text_x - rect.x) - 8
    fitted = theme.truncate_to_width(title, theme.font(title_size), max_w)
    if not fitted:
        return
    img = theme.font(title_size).render(fitted, True, theme.C["text"])
    time_fits = (time_text and rect.h >= TWO_LINE_MIN_H
                 and theme.font(16).size(time_text)[0] <= max_w)
    if time_fits:
        base = rect.y + rect.h / 2
        surface.blit(img, (text_x, base - img.get_height() - 1))
        t_img = theme.font(16).render(time_text, True, theme.C["muted"])
        surface.blit(t_img, (text_x, base + 3))
    else:
        surface.blit(img, (text_x, rect.y + rect.h / 2 - img.get_height() / 2))


def draw_pill(surface, rect: "pygame.Rect", main, label: str,
              size: int = 18) -> bool:
    """整日事件小膠囊（河道泳道頂）：淡底＋淡框＋色點＋中性文字。
    回傳是否畫得下（標題截到空字串就整顆不畫）。"""
    fitted = theme.truncate_to_width(label, theme.font(size), rect.w - 34)
    if not fitted:
        return False
    pygame.draw.rect(surface, fill_color(main), rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, border_color(main), rect, width=1,
                     border_radius=rect.h // 2)
    pygame.draw.circle(surface, main, (rect.x + 13, rect.centery), 4)
    img = theme.font(size).render(fitted, True, theme.C["text"])
    surface.blit(img, img.get_rect(midleft=(rect.x + 24, rect.centery)))
    return True


def draw_lane_label(surface, x: float, cy: float, main, label: str,
                    size: int = 20) -> None:
    """泳道標籤：色點＋中性文字（取代整串飽和彩字）。"""
    pygame.draw.circle(surface, main, (round(x + 5), round(cy)), 5)
    img = theme.font(size).render(label, True, theme.C["text2"])
    surface.blit(img, img.get_rect(midleft=(x + 18, cy)))
