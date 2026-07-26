"""向量圖示繪製，避免依賴字型檔內不一定存在的符號字形（例如 ⚙）。"""

from __future__ import annotations

import math

import pygame


def _polar(cx: float, cy: float, radius: float, angle: float) -> tuple[float, float]:
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def draw_gear(surface: "pygame.Surface", cx: int, cy: int, r: int, color) -> None:
    """在 (cx, cy) 畫一個半徑約 r 的齒輪圖示（設定按鈕用）。

    外圈 8 齒以 pygame.draw.polygon 依角度計算齒形；中心以
    pygame.draw.circle 的 width 參數畫成環形，直接挖空中心，
    不需要知道背景色即可產生鏤空效果。
    """
    teeth = 8
    r_tip = r
    r_root = r * 0.72
    r_hole = r * 0.42

    tip_half = (2 * math.pi / teeth) * 0.26
    root_half = (2 * math.pi / teeth) * 0.42

    for i in range(teeth):
        angle = (2 * math.pi / teeth) * i
        pts = [
            _polar(cx, cy, r_root, angle - root_half),
            _polar(cx, cy, r_tip, angle - tip_half),
            _polar(cx, cy, r_tip, angle + tip_half),
            _polar(cx, cy, r_root, angle + root_half),
        ]
        pygame.draw.polygon(surface, color, pts)

    ring_width = max(2, round(r_root - r_hole))
    pygame.draw.circle(surface, color, (cx, cy), round(r_root), width=ring_width)
