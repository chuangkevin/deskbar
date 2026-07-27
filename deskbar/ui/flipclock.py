import pygame

from deskbar.ui import theme

RADIUS = 14
_cache: dict = {}


def _clear_cache() -> None:
    """主題切換時數字卡快取要整組丟掉——CARD/SPLIT 底色已經烤進 Surface 裡，
    不清掉就會在新主題下繼續顯示舊主題的卡片底色。"""
    _cache.clear()


theme.register_cache_clear(_clear_cache)


def _digit_card(ch: str, w: int, h: int) -> "pygame.Surface":
    key = (ch, w, h)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, theme.C["clock_card"], pygame.Rect(0, 0, w, h),
                         border_radius=RADIUS)
        img = theme.font(int(h * 0.78), bold=True).render(ch, True, theme.C["text"])
        s.blit(img, img.get_rect(center=(w // 2, h // 2)))
        pygame.draw.line(s, theme.C["clock_split"], (2, h // 2), (w - 2, h // 2), 2)
        pygame.draw.rect(s, theme.C["panel_line"], pygame.Rect(0, 0, w, h), 1,
                         border_radius=RADIUS)
        _cache[key] = s
    return s


def _fold_h(progress: float, half: int) -> int:
    """上摺頁高度：前半段（0..0.5）由 half 壓到 1，ease-in——重力把卡面越拉越快。"""
    fold = min(1.0, progress * 2)
    return max(1, int(half * (1 - fold * fold)))


def _drop_h(progress: float, half: int) -> int:
    """下摺頁高度：後半段（0.5..1）由 1 展開到 half，ease-out——落定前減速。"""
    drop = max(0.0, progress * 2 - 1)
    return max(1, int(half * (1 - (1 - drop) ** 2)))


def _shade_alpha(progress: float) -> int:
    """摺頁背光暗度：卡面越接近水平（progress 靠近 0.5）轉離光源越多、越暗，
    完全展開（0 或 1）時歸零——HTC Sense 翻牌的立體感就靠這層漸暗。"""
    return int(120 * (1 - abs(progress - 0.5) * 2))


def _blit_flap(surface, flap, cw: int, fh: int, x: int, y: int, progress: float) -> None:
    scaled = pygame.transform.scale(flap, (cw, fh))
    shade = pygame.Surface((cw, fh), pygame.SRCALPHA)
    shade.fill((0, 0, 0, _shade_alpha(progress)))
    # 陰影要先用 BLEND_RGBA_MIN 夾到卡片自己的 alpha：卡片圓角外是透明像素，
    # 直接蓋滿版黑幕會讓圓角外多出半透明黑方角，翻牌時在淺色主題的白卡上
    # 是一路往下掃的灰色方角污漬（審查實測 bg 242→195）。MIN 之後圓角外
    # alpha 歸零，陰影只落在卡面上。
    shade.blit(scaled, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    scaled.blit(shade, (0, 0))
    surface.blit(scaled, (x, y))


def draw(surface, x: int, y: int, text: str, prev: str, progress: float,
         digit_h: int = 130) -> None:
    w = int(digit_h * 0.72)
    gap = 8
    half = digit_h // 2
    prev = prev if len(prev) == len(text) else text
    for i, ch in enumerate(text):
        cw = w // 2 if ch == ":" else w
        cur = _digit_card(ch, cw, digit_h)
        if progress >= 1.0 or prev[i] == ch or ch == ":":
            surface.blit(cur, (x, y))
        else:
            old = _digit_card(prev[i], cw, digit_h)
            surface.blit(cur, (x, y), area=pygame.Rect(0, 0, cw, half))
            surface.blit(old, (x, y + half), area=pygame.Rect(0, half, cw, half))
            if progress < 0.5:                     # 舊上半加速下摺（背光漸暗）
                flap = old.subsurface(pygame.Rect(0, 0, cw, half))
                fh = _fold_h(progress, half)
                _blit_flap(surface, flap, cw, fh, x, y + half - fh, progress)
            else:                                  # 新下半減速展開（迎光漸亮）
                flap = cur.subsurface(pygame.Rect(0, half, cw, half))
                fh = _drop_h(progress, half)
                _blit_flap(surface, flap, cw, fh, x, y + half, progress)
        x += cw + gap
