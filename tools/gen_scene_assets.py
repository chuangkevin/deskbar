"""離線烘焙氛圍場景的點陣素材（deskbar/assets/scenes/*.png）。

場景引擎 v1 用 pygame 原始幾何直畫，實機驗收：「醜死了」——重蹈了
weatherfx 一版的覆轍（模組 docstring 早寫明：貼紙感的解法是材質）。
本工具沿用 gen_weather_assets 的路數：numpy 烘焙含 per-pixel alpha 的
中性白 PNG，執行期只做「載入→染色→blit＋視差」。

素材（山稜場景 v2）：
- ridge_far/mid/near.png：三層山影。1D fBm 稜線輪廓、軟邊緣、稜線光、
  fBm 岩理明暗、向下漸暗；遠層低對比（大氣透視在染色端疊加）。
- vgrad.png：垂直 alpha 漸層（255→0），天空與晨昏光染色用。

需要 numpy（開發依賴，Pi 不裝）；固定 seed，重跑逐位元一致。

用法：
    .venv/bin/python tools/gen_scene_assets.py
    .venv/bin/python tools/gen_scene_assets.py --out /tmp/preview
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from tools.planet_horizon_assets import generate_planet_horizon_assets  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "deskbar" / "assets" / "scenes"
W, H = 1180, 472           # 比場景區(1118)略寬：留 ±30px 視差擺動餘裕


def _fbm1d(n: int, seed: int, octaves: int = 5, base: int = 3) -> "np.ndarray":
    """一維分形值噪聲 [0,1)：山稜輪廓的骨架。"""
    rng = np.random.default_rng(seed)
    acc = np.zeros(n)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        g = base * 2 ** o + 1
        grid = rng.random(g)
        xs = np.linspace(0, g - 1, n)
        xi = np.minimum(xs.astype(int), g - 2)
        xf = xs - xi
        acc += (grid[xi] * (1 - xf) + grid[xi + 1] * xf) * amp
        total += amp
        amp *= 0.5
    return acc / total


def _fbm2d(w: int, h: int, seed: int, octaves: int = 4, base: int = 6) -> "np.ndarray":
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gw = base * 2 ** o + 1
        gh = max(2, gw * h // w) + 1
        grid = rng.random((gh, gw))
        ys, xs = np.linspace(0, gh - 1, h), np.linspace(0, gw - 1, w)
        yi, xi = np.minimum(ys.astype(int), gh - 2), np.minimum(xs.astype(int), gw - 2)
        yf, xf = (ys - yi)[:, None], (xs - xi)[None, :]
        n = (grid[yi][:, xi] * (1 - yf) * (1 - xf)
             + grid[yi + 1][:, xi] * yf * (1 - xf)
             + grid[yi][:, xi + 1] * (1 - yf) * xf
             + grid[yi + 1][:, xi + 1] * yf * xf)
        acc += n * amp
        total += amp
        amp *= 0.5
    return acc / total


def _save(name: str, rgb: "np.ndarray", alpha: "np.ndarray", out: Path) -> None:
    """rgb [0,1] 灰階（中性白的明暗）、alpha [0,1] → RGBA PNG。"""
    h, w = alpha.shape
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    g = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    arr[..., 0] = arr[..., 1] = arr[..., 2] = g
    arr[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    buf = arr[..., [0, 1, 2, 3]].tobytes()
    img = pygame.image.frombuffer(buf, (w, h), "RGBA")
    surf.blit(img, (0, 0))
    pygame.image.save(surf, str(out / f"{name}.png"))
    print(f"  {name}.png  {w}x{h}")


def gen_ridge(name: str, seed: int, top_frac: float, amp_frac: float,
              tex_strength: float, tex_base: int, out: Path) -> None:
    """一層山影：fBm 稜線 + 軟邊 + 稜線光 + 岩理 + 向下漸暗。"""
    # 山峰要有戲：低頻 fBm 給山體量感，ridged noise（1-|2n-1|）給尖稜，
    # 冪次拉對比——一版純 fBm 烘出來是圓滾滾的霧丘
    mass = _fbm1d(W, seed, octaves=3, base=2)
    ridge_n = 1.0 - np.abs(2.0 * _fbm1d(W, seed + 3, octaves=4, base=6) - 1.0)
    prof = (0.55 * mass + 0.45 * ridge_n ** 1.6) ** 1.25
    ridge = (top_frac + (1 - prof) * amp_frac) * H     # 每欄的稜線 y
    yy = np.arange(H)[:, None].astype(float)
    d = yy - ridge[None, :]                            # 距稜線深度（px，正=山體內）
    alpha = np.clip(d / 2.0, 0.0, 1.0)                 # 2px 軟邊緣（永別了鋸齒）
    tex = _fbm2d(W, H, seed + 7, base=tex_base)
    shade = 1.0 - tex_strength * tex                   # 岩理明暗
    rim = np.clip(1.0 - d / 26.0, 0.0, 1.0) * 0.22     # 稜線下 26px 的受光帶
    depth = np.clip(d / H, 0.0, 1.0) * 0.30            # 越往山腳越沉
    g = np.clip((shade + rim - depth) * 0.86, 0.05, 1.0)
    _save(name, g, alpha, out)


def gen_cumulus(name: str, seed: int, out: Path) -> None:
    """蓬鬆積雲（HTC Sense 的招牌體積雲）：fBm 密度 × 橢圓罩 → alpha，
    頂亮底暗＋邊緣受光。220×120，執行期染色縮放。"""
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
    _save(name, lum, alpha, out)


def gen_sun_ball(out: Path) -> None:
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
    _save("sun_ball", lum, alpha, out)


def gen_vgrad(out: Path) -> None:
    a = np.linspace(1.0, 0.0, H)[:, None].repeat(8, axis=1)
    _save("vgrad", np.ones((H, 8)), a, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pygame.init()
    print(f"烘焙場景素材 → {args.out}")
    #                 seed 高度     振幅    岩理強度 岩理頻率
    gen_ridge("ridge_far", 101, 0.30, 0.26, 0.10, 5, args.out)
    gen_ridge("ridge_mid", 202, 0.44, 0.30, 0.16, 7, args.out)
    gen_ridge("ridge_near", 303, 0.62, 0.30, 0.20, 10, args.out)
    gen_vgrad(args.out)
    gen_cumulus("cumulus_0", 11, args.out)
    gen_cumulus("cumulus_1", 22, args.out)
    gen_sun_ball(args.out)
    generate_planet_horizon_assets(args.out)
    print("完成。")


if __name__ == "__main__":
    main()
