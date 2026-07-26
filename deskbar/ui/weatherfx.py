"""左面板天氣微動態——刻意的低幀率「緩慢氛圍」背景層，不追求流暢動畫。

呼叫端（dashboard._render_panel）在畫時鐘/文字「之前」呼叫 draw()，把這層
當成左面板的背景氛圍：雨天灑幾條斜線、多雲橫移幾團半透明橢圓、晴天在時鐘
後方吐兩圈呼吸光暈。座標系統以 (x0, 0)-(x0+w, h) 的矩形為畫布，實際繪製一律
透過 surface.subsurface() 裁切，任何座標算錯也不會畫出這個矩形範圍——不需要
呼叫端自己再包一層裁切。

節奏鐵則：tick 由呼叫端每秒 +1 遞增後傳入，本模組只依 tick 做純函式運算，
不得讀 pygame.time / time.time() 自行拉高幀率——重繪頻率完全由呼叫端的主迴圈
掌控（idle tick(10) 一秒最多重繪一次，天氣氛圍自然跟著一秒動一格）。

快取鐵則：不建立無界成長的容器（例如一直塞新 key 的 dict）。雲層橢圓的形狀
（大小/alpha）不隨 tick 變化，只有位置在動，所以用「單一 slot」快取最近一次
(code, w, h) 對應的底圖——同一組參數重複呼叫不必重繪橢圓，換了參數就整個
覆蓋掉舊的，物理上永遠只存在一張，不會無限長大（比照 deskbar/ui/qr.py 的
_cache_key/_cache_surface 寫法）。
"""

from __future__ import annotations

import math

import pygame

from deskbar.ui import theme

RAIN_CODES = set(range(51, 68)) | set(range(80, 83)) | set(range(95, 100))
CLOUD_CODES = set(range(1, 4)) | {45, 48}
CLEAR_CODES = {0}

_RAIN_COLOR = theme.col((70, 90, 120))
_CLOUD_COLOR = theme.col((205, 210, 220))
_GLOW_COLOR = theme.col((255, 214, 140))

_RAIN_N = 12
_CLOUD_N = 3
_CLOUD_BLOB_SIZE = (140, 64)     # (寬, 高)，橢圓底圖固定尺寸，不隨面板 w/h 縮放
_CLOUD_ALPHA = 28
_GLOW_RINGS = ((70, 10), (44, 18))   # (半徑, alpha)：外圈較淡、內圈靠近時鐘較亮

# 單一 slot 快取：整個模組同一時間最多只存在一張底圖，換 key 就整張覆蓋掉，
# 不是會持續長大的 dict／list。build_count 供測試驗證「真的快取住了」。
_cache_key: "tuple[int, int, int] | None" = None
_cache_surface: "pygame.Surface | None" = None
build_count = 0


def draw(surface, code: int, tick: int, x0: int = 0, w: int = 400, h: int = 480) -> None:
    """在 surface 的 (x0, 0)-(x0+w, h) 矩形內畫出 code 對應的天氣氛圍層。

    code 對不到雨/雲/晴任一組就完全不畫（保留背景原樣）；tick 每次呼叫應由
    呼叫端遞增 1（每秒一次），本函式本身是純函式、不含任何計時邏輯。
    """
    if w <= 0 or h <= 0:
        return
    rect = pygame.Rect(x0, 0, w, h).clip(surface.get_rect())
    if rect.width <= 0 or rect.height <= 0:
        return
    panel = surface.subsurface(rect)
    if code in RAIN_CODES:
        _draw_rain(panel, tick, w, h)
    elif code in CLOUD_CODES:
        _draw_clouds(panel, code, tick, w, h)
    elif code in CLEAR_CODES:
        _draw_glow(panel, tick, w, h)
    # 其餘 code：刻意不畫任何東西，維持背景原樣。


def _draw_rain(panel, tick: int, w: int, h: int) -> None:
    for i in range(_RAIN_N):
        y = (tick * 7 + i * 37) % (h + 40)
        x = (i * 53 + 19) % w        # x 只由 i 決定（固定線位），只有 y 隨 tick 落下
        pygame.draw.line(panel, _RAIN_COLOR, (x, y), (x - 6, y + 14), 2)


def _draw_clouds(panel, code: int, tick: int, w: int, h: int) -> None:
    blob = _get_cloud_blob(code, w, h)
    bw, bh = blob.get_size()
    for i in range(_CLOUD_N):
        cx = (tick * 2 + i * 90) % (w + 160) - 80
        cy = int(h * (0.12 + i * 0.16))
        panel.blit(blob, (cx - bw // 2, cy - bh // 2))


def _get_cloud_blob(code: int, w: int, h: int) -> "pygame.Surface":
    global _cache_key, _cache_surface
    key = (code, w, h)
    if _cache_key != key or _cache_surface is None:
        _cache_surface = _build_cloud_blob()
        _cache_key = key
    return _cache_surface


def _build_cloud_blob() -> "pygame.Surface":
    global build_count
    build_count += 1
    bw, bh = _CLOUD_BLOB_SIZE
    blob = pygame.Surface((bw, bh), pygame.SRCALPHA)
    pygame.draw.ellipse(blob, (*_CLOUD_COLOR, _CLOUD_ALPHA), blob.get_rect())
    return blob


def _draw_glow(panel, tick: int, w: int, h: int) -> None:
    breathe = math.sin(tick / 6) * 6      # 半徑呼吸 ±6px
    cx = w // 2
    cy = int(h * 0.21)                    # 大致對齊左面板時鐘卡片的垂直位置
    for base_r, alpha in _GLOW_RINGS:
        r = max(1, int(round(base_r + breathe)))
        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*_GLOW_COLOR, alpha), (r, r), r)
        panel.blit(glow, (cx - r, cy - r))
