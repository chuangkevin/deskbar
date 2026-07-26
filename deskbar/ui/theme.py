import os

import pygame

C = {
    "bg": (15, 15, 15), "panel_line": (38, 38, 38), "grid": (36, 36, 36),
    "text": (236, 236, 236), "text2": (168, 168, 168), "muted": (111, 111, 111),
    "now": (240, 153, 123), "now_text": (74, 27, 12),
    "warn": (240, 149, 149), "card": (26, 26, 26),
}
ACCOUNT_COLORS = [
    ((93, 202, 165), (8, 80, 65)),     # teal
    ((133, 183, 235), (12, 68, 124)),  # blue
    ((175, 169, 236), (60, 52, 137)),  # purple
    ((240, 153, 123), (74, 27, 12)),   # coral
]
_FONT_PATHS = [
    os.environ.get("DESKBAR_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_font_cache: dict = {}


def font(size: int) -> "pygame.font.Font":
    if not pygame.font.get_init():
        pygame.font.init()
        _font_cache.clear()
    if size not in _font_cache:
        f = None
        for p in _FONT_PATHS:
            if p and os.path.exists(p):
                f = pygame.font.Font(p, size)
                break
        if f is None:
            name = pygame.font.match_font("pingfangtc,pingfang,helvetica,arial") or None
            f = pygame.font.Font(name, size)
        _font_cache[size] = f
    return _font_cache[size]


def account_color(idx: int):
    return ACCOUNT_COLORS[idx % len(ACCOUNT_COLORS)]
