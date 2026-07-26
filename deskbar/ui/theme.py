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

# BGR 色板開關：某些面板排線只吃 BGR 順序，接反了全螢幕顏色就會錯置。
# DESKBAR_BGR=1 時，theme 載入當下就把 C／ACCOUNT_COLORS 所有顏色 (r,g,b)→(b,g,r)；
# 沒設就完全不碰，dev 模式零行為差異。只在「theme 載入時」讀一次 env，
# 之後 col() 沿用同一個旗標，不必每次呼叫都重新查 os.environ。
_BGR = os.environ.get("DESKBAR_BGR") == "1"


def col(rgb):
    """給 repo 內其他模組寫死的彩色 RGB(A) 常量包一層：DESKBAR_BGR=1 時交換 R/B
    通道，否則原樣傳回。灰階對稱色（r==g==b）交換前後不變，這類常量可以不包，
    包了也無害——這支只負責「開關開著時才動手」，不負責判斷要不要包。"""
    if _BGR:
        r, g, b, *rest = rgb
        return (b, g, r, *rest)
    return tuple(rgb)


if _BGR:
    C = {k: col(v) for k, v in C.items()}
    ACCOUNT_COLORS = [(col(main), col(dark)) for main, dark in ACCOUNT_COLORS]
_FONT_PATHS = [
    os.environ.get("DESKBAR_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
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
