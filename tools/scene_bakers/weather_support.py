"""Bake small neutral Sense-weather support sprites used outside scene rotation.

這三張（cumulus_0/1、sun_ball）不在十場景輪播裡，是 deskbar/ui/sensewx.py 的
天氣素材，執行期才染色。烘焙式沿用基線 tools/gen_scene_assets.py 的 numpy 路數
——不是為了懷舊，是因為每個係數都對應一次實機驗收的病灶（見各 baker 註解）。
改動這裡請重跑 tests/test_sunstrip_scenes_flow.py 的雲邊界回歸測試。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _fbm2d(width: int, height: int, seed: int, octaves: int = 4,
           base: int = 6) -> FloatArray:
    """二維分形值噪聲 [0,1)：雲的密度骨架。

    刻意保留基線的雙線性插值與 grid 尺寸算式（而非 common.fbm 的 smoothstep
    版本）——兩者噪聲場不同，換過去等於重畫雲，產出也不再與基線逐位元一致。
    """
    rng = np.random.default_rng(seed)
    acc = np.zeros((height, width))
    amp, total = 1.0, 0.0
    for octave in range(octaves):
        gw = base * 2 ** octave + 1
        gh = max(2, gw * height // width) + 1
        grid = rng.random((gh, gw))
        ys, xs = np.linspace(0, gh - 1, height), np.linspace(0, gw - 1, width)
        yi, xi = np.minimum(ys.astype(int), gh - 2), np.minimum(xs.astype(int), gw - 2)
        yf, xf = (ys - yi)[:, None], (xs - xi)[None, :]
        acc += (grid[yi][:, xi] * (1 - yf) * (1 - xf)
                + grid[yi + 1][:, xi] * yf * (1 - xf)
                + grid[yi][:, xi + 1] * (1 - yf) * xf
                + grid[yi + 1][:, xi + 1] * yf * xf) * amp
        total += amp
        amp *= 0.5
    return acc / total


def _save(path: Path, rgb: FloatArray, alpha: FloatArray) -> None:
    """rgb [0,1] 灰階（中性白的明暗）、alpha [0,1] → RGBA PNG。"""
    height, width = alpha.shape
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    grey = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    arr[..., 0] = arr[..., 1] = arr[..., 2] = grey
    arr[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    image = pygame.image.frombuffer(arr.tobytes(), (width, height), "RGBA")
    surface.blit(image, (0, 0))
    pygame.image.save(surface, str(path))


def _cloud(path: Path, seed: int) -> None:
    """蓬鬆積雲（HTC Sense 的招牌體積雲）：fBm 密度 × 橢圓罩 → alpha，
    頂亮底暗＋邊緣受光。240×132，執行期染色縮放。"""
    cw, ch = 240, 132
    den = _fbm2d(cw, ch, seed, octaves=5, base=4)
    yy, xx = np.mgrid[0:ch, 0:cw]
    ex = (xx - cw / 2) / (cw * 0.42)
    ey = (yy - ch * 0.58) / (ch * 0.46)
    r = np.sqrt(ex ** 2 + ey ** 2)
    alpha = np.clip((den * 1.5 + (1 - r) * 0.9 - 0.90) * 1.8, 0.0, 1.0)
    # 邊界羽化窗：alpha 在畫布四邊 14/10px 內強制壓到 0。沒有這個，fBm
    # 密度碰到素材矩形邊緣被硬切——bbox 直邊在深色背景上看不出來，疊到
    # 白色翻牌卡上就顯形成「奇怪的方塊」（實機三次驗收的真正病灶）
    fx = np.clip(xx / 14.0, 0, 1) * np.clip((cw - 1 - xx) / 14.0, 0, 1)
    fy = np.clip(yy / 10.0, 0, 1) * np.clip((ch - 1 - yy) / 10.0, 0, 1)
    alpha *= (fx * fy) ** 0.8
    # 內部保留 fBm 密度起伏（一版內部全 1.0＝死白一片，把時鐘埋成白板——
    # 實機驗收「直接爛掉」），邊緣仍然蓬鬆
    alpha *= 0.80 + 0.20 * den
    # 雲腹要有明確的灰藍陰影（頂 1.0 → 腹 ~0.74）：白卡上的雲全靠這個
    # 陰影才「看得見」——參考圖 Sense 雲的肚子就是灰的。純白版（0.86 地板）
    # 疊白卡＝隱形橡皮擦，數字被擦掉還看不出是雲
    lum = np.clip(0.74 + 0.26 * (1 - yy / ch) ** 1.3 + 0.08 * den - 0.06 * r,
                  0.0, 1.0)
    _save(path, lum, alpha)


def _sun(path: Path) -> None:
    """亮面太陽球：實心圓＋上緣高光＋外圈光暈（中性白，執行期染橘）。"""
    n = 160
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.sqrt((xx - n / 2) ** 2 + (yy - n / 2) ** 2)
    core_r = 44.0
    core = np.clip((core_r - r) / 2.0, 0.0, 1.0)          # 軟邊實心球
    glow = np.clip(1.0 - (r - core_r) / 34.0, 0.0, 1.0) ** 2 * 0.55
    alpha = np.clip(core + np.where(r > core_r, glow, 0.0), 0.0, 1.0)
    gloss = np.clip(1.0 - np.sqrt((xx - n / 2) ** 2
                                  + (yy - n * 0.36) ** 2) / (core_r * 0.9),
                    0.0, 1.0) * 0.35
    lum = np.clip(0.86 + gloss - np.clip((r / core_r - 0.55), 0, 1) * 0.18,
                  0.0, 1.0) * (core > 0) + (core <= 0) * 0.95
    _save(path, lum, alpha)


def generate_weather_support_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _cloud(out / "cumulus_0.png", 11)
    _cloud(out / "cumulus_1.png", 22)
    _sun(out / "sun_ball.png")
