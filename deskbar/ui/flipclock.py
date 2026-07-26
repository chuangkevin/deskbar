import pygame

from deskbar.ui import theme

CARD = (28, 28, 28)
SPLIT = (12, 12, 12)


def _digit_card(ch: str, w: int, h: int) -> "pygame.Surface":
    s = pygame.Surface((w, h))
    s.fill(CARD)
    img = theme.font(int(h * 0.78)).render(ch, True, theme.C["text"])
    s.blit(img, img.get_rect(center=(w // 2, h // 2)))
    pygame.draw.line(s, SPLIT, (0, h // 2), (w, h // 2), 2)
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
