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
        img = theme.font(int(h * 0.78)).render(ch, True, theme.C["text"])
        s.blit(img, img.get_rect(center=(w // 2, h // 2)))
        pygame.draw.line(s, theme.C["clock_split"], (2, h // 2), (w - 2, h // 2), 2)
        pygame.draw.rect(s, theme.C["panel_line"], pygame.Rect(0, 0, w, h), 1,
                         border_radius=RADIUS)
        _cache[key] = s
    return s


def draw(surface, x: int, y: int, text: str, prev: str, progress: float,
         digit_h: int = 130) -> None:
    w = int(digit_h * 0.72)
    gap = 8
    prev = prev if len(prev) == len(text) else text
    for i, ch in enumerate(text):
        cw = w // 2 if ch == ":" else w
        cur = _digit_card(ch, cw, digit_h)
        if progress >= 1.0 or prev[i] == ch or ch == ":":
            surface.blit(cur, (x, y))
        else:
            old = _digit_card(prev[i], cw, digit_h)
            surface.blit(cur, (x, y), area=pygame.Rect(0, 0, cw, digit_h // 2))
            surface.blit(old, (x, y + digit_h // 2),
                         area=pygame.Rect(0, digit_h // 2, cw, digit_h // 2))
            if progress < 0.5:                     # 舊上半往下壓
                flap = old.subsurface(pygame.Rect(0, 0, cw, digit_h // 2))
                fh = max(1, int((digit_h // 2) * (1 - progress * 2)))
                surface.blit(pygame.transform.scale(flap, (cw, fh)),
                             (x, y + digit_h // 2 - fh))
            else:                                  # 新下半往下展開
                flap = cur.subsurface(pygame.Rect(0, digit_h // 2, cw, digit_h // 2))
                fh = max(1, int((digit_h // 2) * (progress * 2 - 1)))
                surface.blit(pygame.transform.scale(flap, (cw, fh)),
                             (x, y + digit_h // 2))
        x += cw + gap
