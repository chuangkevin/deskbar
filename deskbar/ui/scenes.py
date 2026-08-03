"""氛圍場景引擎：中欄的「非工具向」動態畫面（研究定案的 Wallpaper Engine 精神）。

第一個場景是流場粒子（flow field）：一群粒子沿著緩慢漂移的向量場游走，
留下漸淡的軌跡——低頻演變、永不重複，是研究裡「耐看不膩」的教科書手法
（Perlin flow field 的廉價近似：三個不同尺度的正弦疊加，Pi Zero 2W 上
每幀只有 ~90 次三角函數）。

- 每天換一幅：粒子配置與場相位以「日序」做種子，今天的流場全世界只有這一幅
- 隨時間變調：調色盤跟著晝夜走（白晝墨青、晨昏琥珀、夜裡靛藍星白）
- 節奏鐵則同 weatherfx：t 是呼叫端傳入的單調浮點秒，本模組不自行計時
- 狀態（軌跡面、粒子）放呼叫端持有的 ui dict（new_state()），跨幀累積

中欄自動排程（忙→場景、閒→便條/行事曆）在 app._check_flow_center；
本模組只管畫。點場景任意處＝手動切走（toggle_center）。
"""

from __future__ import annotations

import math

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit, theme

# 中欄場景區：x 避開左欄(400)與右欄(1520)，y 讓出頂緣日光帶(8px)
AREA = Rect(402, 8, 1118, 472)
PART_N = 90
FPS = 10                     # 場景氛圍幀率（app 的 ambient 分支用）
_FADE_A = 5                  # 軌跡每幀退淡量（alpha 減法）；越小尾巴越長


def new_state() -> dict:
    return {"trail": None, "parts": [], "seed": 0, "t_last": None}


def _h(*args) -> float:
    """黃金比例雜湊 → [0,1)，同 weatherfx（位置/速度/色相全走這裡）。"""
    x = 0x9E3779B9
    for a in args:
        x = (x ^ (int(a) & 0xFFFFFFFF)) * 2654435761 & 0xFFFFFFFF
        x ^= x >> 15
    return ((x * 2246822519 & 0xFFFFFFFF) >> 8) / float(1 << 24)


def _angle(x: float, y: float, t: float, seed: float) -> float:
    """三尺度正弦疊加的向量場：低頻定大構圖、中頻擾動、時間項極慢漂移。"""
    return 2.1 * (math.sin(x * 0.0021 + t * 0.031 + seed)
                  + math.cos(y * 0.0034 - t * 0.023 + seed * 1.7)
                  + math.sin((x + y) * 0.0012 + t * 0.017))


def _palette(now) -> tuple:
    """晝夜調色盤：(主色, 副色)——粒子在兩色間按各自的色相參數內插。"""
    h = now.hour + now.minute / 60.0
    if theme.current_theme() == "light":
        day = ((70, 110, 150), (150, 120, 80))
        dusk = ((190, 120, 60), (120, 100, 150))
        night = ((90, 100, 150), (150, 140, 170))
    else:
        day = ((96, 156, 190), (170, 150, 100))
        dusk = ((220, 140, 70), (130, 110, 190))
        night = ((100, 120, 210), (200, 208, 235))
    if 8 <= h < 16:
        return day
    if 5 <= h < 8 or 16 <= h < 19:
        return dusk
    return night


def _lerp(a, b, p: float) -> tuple:
    return tuple(round(a[i] + (b[i] - a[i]) * p) for i in range(3))


def render(surface, ui: dict, now, t: float) -> list:
    """畫一幀到 AREA；回傳 hits（整區一個 toggle_center——場景沒有標題列，
    點任何地方＝切走，這是唯一的逃生口）。"""
    day_seed = now.year * 400 + now.timetuple().tm_yday      # 每天換一幅
    if (ui["trail"] is None or ui["seed"] != day_seed
            or ui["trail"].get_size() != (AREA.w, AREA.h)):
        ui["trail"] = pygame.Surface((int(AREA.w), int(AREA.h)), pygame.SRCALPHA)
        ui["seed"] = day_seed
        ui["parts"] = [[_h(i, day_seed) * AREA.w, _h(i, day_seed, 7) * AREA.h,
                        _h(i, day_seed, 3)] for i in range(PART_N)]
        ui["t_last"] = None
    dt = 1.0 / FPS if ui["t_last"] is None else max(0.0, min(0.25, t - ui["t_last"]))
    ui["t_last"] = t
    trail = ui["trail"]
    trail.fill((0, 0, 0, _FADE_A), special_flags=pygame.BLEND_RGBA_SUB)
    c0, c1 = _palette(now)
    phase = (ui["seed"] % 97) * 0.13
    for i, p in enumerate(ui["parts"]):
        ang = _angle(p[0], p[1], t, phase)
        spd = 26 + p[2] * 34
        nx = p[0] + math.cos(ang) * spd * dt
        ny = p[1] + math.sin(ang) * spd * dt
        if 0 <= nx < AREA.w and 0 <= ny < AREA.h:
            color = _lerp(c0, c1, p[2])
            pygame.draw.line(trail, (*color, 200),
                             (p[0], p[1]), (nx, ny), 2)
            p[0], p[1] = nx, ny
        else:
            # 出界＝在別處重生（種子摻入時間片，重生點不重複但可重現）
            cell = int(t * 3) + i
            p[0] = _h(cell, ui["seed"], 11) * AREA.w
            p[1] = _h(cell, ui["seed"], 12) * AREA.h
    surface.fill(theme.C["bg"], pygame.Rect(int(AREA.x), int(AREA.y),
                                            int(AREA.w), int(AREA.h)))
    surface.blit(trail, (int(AREA.x), int(AREA.y)))
    return [Hit(Rect(AREA.x, AREA.y, AREA.w, AREA.h), "toggle_center", None)]
