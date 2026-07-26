"""左面板天氣微動態——刻意的低幀率（1fps）「緩慢氛圍」效果，不追求流暢動畫。

App 主迴圈每秒把 tick 加 1（重開機歸零無妨，純視覺、不落地），dashboard._render_panel
在畫時鐘/文字之前呼叫 draw() 當背景層。所有繪製都夾在左面板 subsurface（0~PANEL_W px）
內，任何座標算錯也不會畫出左面板，滿足「粒子/特效只畫在左面板」鐵則。
"""
import math

import pygame

from deskbar.ui import theme

PANEL_W = 480
PANEL_H = 480
MAX_PARTICLES = 40          # 設計上限；目前雨天用 15 條，遠低於預算，留給未來效果擴充

RAIN_CODES = set(range(51, 68)) | set(range(80, 83))    # 毛毛雨/雨/陣雨
CLOUD_CODES = {1, 2, 3, 45, 48}                          # 晴時多雲/多雲/陰/霧
CLEAR_CODES = {0}                                        # 晴

_RAIN_COLOR = theme.col((110, 140, 175))
_CLOUD_COLOR = theme.col((72, 72, 80))
_GLOW_COLOR = theme.col((255, 214, 140))
_GLOW_CENTER = (90, 100)     # 大致對齊左上角時鐘卡片（座標，非顏色，不需 col()）


def draw(surface, code: int, tick: int) -> None:
    """在 surface 左面板（0~480px）畫對應天氣代碼的微動態；tick 每秒 +1。"""
    panel = surface.subsurface(pygame.Rect(0, 0, PANEL_W, PANEL_H))
    if code in RAIN_CODES:
        _draw_rain(panel, tick)
    elif code in CLOUD_CODES:
        _draw_clouds(panel, tick)
    elif code in CLEAR_CODES:
        _draw_glow(panel, tick)


def _draw_rain(panel, tick: int) -> None:
    n = 15
    for i in range(n):
        seed = i * 37
        speed = 47 + (i % 5) * 11        # 每條線速度略有差異，避免整排同步下墜
        y = (tick * speed + seed) % PANEL_H
        x = (seed * 13) % PANEL_W
        pygame.draw.line(panel, _RAIN_COLOR, (x, y), (x - 6, y + 14), 2)


def _draw_clouds(panel, tick: int) -> None:
    for i in range(3):
        seed = i * 97
        speed = 6 + i * 3
        cx = (tick * speed + seed) % (PANEL_W + 140) - 70
        cy = 60 + i * 55
        blob = pygame.Surface((140, 60), pygame.SRCALPHA)
        pygame.draw.ellipse(blob, (*_CLOUD_COLOR, 90), blob.get_rect())
        panel.blit(blob, (cx - 70, cy - 30))


def _draw_glow(panel, tick: int) -> None:
    breathe = math.sin(tick * 0.5) * 8       # 半徑微幅呼吸
    for base_r, alpha in ((70, 24), (46, 40)):
        r = int(base_r + breathe)
        if r <= 0:
            continue
        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*_GLOW_COLOR, alpha), (r, r), r)
        panel.blit(glow, (_GLOW_CENTER[0] - r, _GLOW_CENTER[1] - r))
