"""設定頁 QR code 繪製。純 Python qrcode 套件（不依賴 pillow）。

只快取「最後一次」(text, size) 產生的 Surface：QR 內容固定不變（見
WEB_URL），沒有需要保留多組快取的情境，單一 slot 就能避免每幀重算。
"""

from __future__ import annotations

import os

import pygame
import qrcode

from deskbar.ui import theme

# 未來要改網址只改這裡。
# 實際網址由裝置端環境變數 DESKBAR_WEB_URL 指定（不入版控）；未設定時用區網預設。
WEB_URL = os.environ.get("DESKBAR_WEB_URL", "http://deskbar.local:8080")

_cache_key: tuple[str, int] | None = None
_cache_surface: "pygame.Surface | None" = None

# 供測試驗證是否真的命中快取（每次實際重算才會 +1）。
build_count = 0


def _clear_cache() -> None:
    """QR 底色兩主題都固定白底黑點（不隨主題變化），理論上不必清；主題切換時
    仍登記進來保險清空一次，避免未來有人改成主題色卻忘了補這支快取失效。"""
    global _cache_key, _cache_surface
    _cache_key = None
    _cache_surface = None


theme.register_cache_clear(_clear_cache)


def _build_surface(text: str, size: int) -> "pygame.Surface":
    global build_count
    build_count += 1

    qr = qrcode.QRCode(box_size=1, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)

    cell = max(1, size // n)
    drawn = cell * n
    offset = (size - drawn) // 2

    surf = pygame.Surface((size, size))
    surf.fill((255, 255, 255))
    for row_idx, row in enumerate(matrix):
        for col_idx, dark in enumerate(row):
            if dark:
                pygame.draw.rect(
                    surf, (0, 0, 0),
                    pygame.Rect(offset + col_idx * cell, offset + row_idx * cell, cell, cell),
                )
    return surf


def draw_qr(surface: "pygame.Surface", x: int, y: int, size: int, text: str) -> None:
    """在 (x, y) 畫出邊長 size 的 QR code（白底黑點）。"""
    global _cache_key, _cache_surface
    key = (text, size)
    if _cache_key != key or _cache_surface is None:
        _cache_surface = _build_surface(text, size)
        _cache_key = key
    surface.blit(_cache_surface, (x, y))
