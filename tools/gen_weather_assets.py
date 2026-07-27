"""離線烘焙 weatherfx 的點陣素材（deskbar/assets/weatherfx/*.png）。

「程式員美術天花板」的解法：pygame 圓/線畫出來的場景永遠是貼紙感，真實感
來自材質——雲要有 fBm 噪聲的絮狀密度、光暈要有高斯衰減、水滴要有透鏡漸層
與高光。這些在 Pi Zero 2W 上不可能逐幀算，所以全部在開發機離線烘焙成含
per-pixel alpha 的中性白 PNG，執行期 weatherfx 只做「載入→依主題染色→blit」，
比原本逐幀畫幾何還便宜。

需要 numpy（開發依賴，Pi 不裝）；輸出用固定 seed，重跑逐位元一致、可 diff。

用法：
    .venv/bin/python tools/gen_weather_assets.py          # 寫入 deskbar/assets/weatherfx
    .venv/bin/python tools/gen_weather_assets.py --out /tmp/preview
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pygame  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "deskbar" / "assets" / "weatherfx"


# ---------------------------------------------------------------- numpy 基礎工具

def fbm(w: int, h: int, seed: int, octaves: int = 4, base: int = 4) -> "np.ndarray":
    """分形值噪聲 [0,1)：粗網格隨機值雙線性放大、逐八度疊加。"""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gw, gh = base * 2 ** o + 1, max(2, (base * 2 ** o) * h // max(1, w)) + 1
        grid = rng.random((gh, gw))
        ys = np.linspace(0, gh - 1, h)
        xs = np.linspace(0, gw - 1, w)
        yi = np.minimum(ys.astype(int), gh - 2)
        xi = np.minimum(xs.astype(int), gw - 2)
        yf = (ys - yi)[:, None]
        xf = (xs - xi)[None, :]
        n = (grid[yi][:, xi] * (1 - yf) * (1 - xf) + grid[yi + 1][:, xi] * yf * (1 - xf)
             + grid[yi][:, xi + 1] * (1 - yf) * xf + grid[yi + 1][:, xi + 1] * yf * xf)
        acc += n * amp
        total += amp
        amp *= 0.5
    return acc / total


def box_blur(a: "np.ndarray", r: int, passes: int = 3) -> "np.ndarray":
    """分離式 box blur ×N ≈ 高斯。cumsum 實作，r 為半徑。"""
    for _ in range(passes):
        for axis in (0, 1):
            n = a.shape[axis]
            c = np.cumsum(a, axis=axis)
            pad = np.take(c, [-1], axis=axis)
            hi = np.concatenate([np.take(c, range(r, n), axis=axis),
                                 np.repeat(pad, r, axis=axis)], axis=axis)
            lo = np.concatenate([np.zeros_like(np.take(c, range(r + 1), axis=axis)),
                                 np.take(c, range(0, n - r - 1), axis=axis)], axis=axis)
            a = (hi - lo) / (2 * r + 1)
    return a


def radial(w: int, h: int, cx: float = None, cy: float = None) -> "np.ndarray":
    """每像素到中心的距離（px）。"""
    cx = (w - 1) / 2 if cx is None else cx
    cy = (h - 1) / 2 if cy is None else cy
    y, x = np.mgrid[0:h, 0:w]
    return np.hypot(x - cx, y - cy)


def save_rgba(path: Path, rgb: "np.ndarray", alpha: "np.ndarray") -> None:
    """rgb: (h,w,3) 或 (h,w) 灰階 0..1；alpha: (h,w) 0..1。"""
    h, w = alpha.shape
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[:, :, None], 3, axis=2)
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    buf = np.zeros((h, w, 4), dtype=np.uint8)
    buf[:, :, :3] = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    buf[:, :, 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    view = pygame.surfarray.pixels_alpha(surf)
    view[:, :] = buf[:, :, 3].T
    del view
    rgb_view = pygame.surfarray.pixels3d(surf)
    rgb_view[:, :, :] = buf[:, :, :3].transpose(1, 0, 2)
    del rgb_view
    pygame.image.save(surf, str(path))
    print(path)


def smoothstep(e0: float, e1: float, x: "np.ndarray") -> "np.ndarray":
    """支援遞減邊界（e1 < e0 ＝「越小越裡面」的遮罩）。除零保護不能用
    max(1e-9, denom)——那會把負分母翻正、整張遮罩反相（雲變滿版矩形、
    月亮挖空的事故根因）。"""
    denom = e1 - e0
    if abs(denom) < 1e-9:
        denom = 1e-9
    t = np.clip((x - e0) / denom, 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- 各素材

def gen_cloud(out: Path, name: str, seed: int, layout) -> None:
    """絮狀雲：剪影遮罩（bump 群＋內縮底座）→模糊→乘 fBm 密度；RGB 帶
    自體陰影（頂亮底暗）＋噪聲細節。380×150。"""
    w, h = 380, 150
    mask = np.zeros((h, w))
    yy, xx = np.mgrid[0:h, 0:w]
    for fx, fy, fr in layout:
        d = np.hypot(xx - fx * w, yy - fy * h)
        mask = np.maximum(mask, smoothstep(fr * h + 8, fr * h - 10, d))
    # 內縮平底：底座矩形（圓端用兩顆圓補）
    bx0, bx1, by0, by1 = 0.10 * w, 0.90 * w, 0.52 * h, 0.86 * h
    rrad = (by1 - by0) / 2
    inside = ((xx > bx0) & (xx < bx1)
              & (yy > by0) & (yy < by1)).astype(float)
    for ex in (bx0, bx1):
        d = np.hypot(xx - ex, yy - (by0 + by1) / 2)
        inside = np.maximum(inside, smoothstep(rrad + 6, rrad - 8, d))
    mask = np.maximum(mask, inside)
    mask = box_blur(mask, 6)
    tex = fbm(w, h, seed, octaves=5, base=5)
    density = mask * (0.42 + 0.58 * smoothstep(0.25, 0.9, tex * 0.7 + mask * 0.45))
    alpha = np.clip(density, 0, 1) * 0.88
    # 自體陰影：頂受光、底转暗；再乘一點噪聲讓明暗絮狀化
    shade = 1.0 - 0.34 * smoothstep(0.30, 0.95, yy / h)
    rgb = (0.72 + 0.28 * tex) * shade
    save_rgba(out / f"{name}.png", rgb, alpha)


def gen_glow(out: Path) -> None:
    n = 240
    r = radial(n, n)
    alpha = np.exp(-(r / (n * 0.23)) ** 2)
    save_rgba(out / "glow.png", np.ones((n, n)), alpha)


def gen_rays(out: Path) -> None:
    """12 道錐形光芒（旋轉對稱），角向高斯×徑向包絡，執行期整張旋轉。"""
    n = 300
    r = radial(n, n)
    y, x = np.mgrid[0:n, 0:n]
    ang = np.arctan2(y - (n - 1) / 2, x - (n - 1) / 2)
    sector = (ang % (math.pi / 6)) - math.pi / 12       # 距最近光芒中心的角差
    # 角寬隨半徑縮小（近圓心寬、末端尖）→ 錐形
    ang_sigma = 0.10 * (1 - 0.55 * np.clip(r / (n * 0.5), 0, 1)) + 0.015
    angular = np.exp(-(sector / ang_sigma) ** 2)
    envelope = smoothstep(n * 0.13, n * 0.22, r) * (1 - smoothstep(n * 0.30, n * 0.495, r))
    alpha = angular * envelope * 0.85
    save_rgba(out / "rays.png", np.ones((n, n)), alpha)


def gen_moon(out: Path) -> None:
    n = 96
    r = radial(n, n)
    R = n * 0.42
    disc = smoothstep(R + 1.5, R - 1.5, r)
    limb = 1 - 0.38 * np.clip(r / R, 0, 1) ** 2         # 邊緣減光
    tex = fbm(n, n, seed=7, octaves=4, base=4)
    surface = 0.82 + 0.18 * tex
    for cx, cy, cr, depth in ((0.58, 0.55, 0.13, 0.30), (0.38, 0.32, 0.09, 0.24),
                              (0.45, 0.68, 0.07, 0.22), (0.66, 0.30, 0.06, 0.18)):
        d = radial(n, n, cx * n, cy * n)
        crater = smoothstep(cr * n + 2, cr * n - 2, d)
        surface = surface * (1 - depth * crater)
    save_rgba(out / "moon.png", surface * limb, disc)


def gen_star(out: Path) -> None:
    n = 9
    r = radial(n, n)
    save_rgba(out / "star.png", np.ones((n, n)), np.exp(-(r / 1.6) ** 2))
    m = 19
    y, x = np.mgrid[0:m, 0:m]
    c = (m - 1) / 2
    arm = (np.exp(-((y - c) / 0.8) ** 2) + np.exp(-((x - c) / 0.8) ** 2))
    fall = np.exp(-(radial(m, m) / (m * 0.42)) ** 2)
    save_rgba(out / "flare.png", np.ones((m, m)), np.clip(arm * fall * 0.8, 0, 1))


def gen_flake(out: Path) -> None:
    n = 17
    y, x = np.mgrid[0:n, 0:n]
    c = (n - 1) / 2
    alpha = np.zeros((n, n))
    for k in range(6):
        a = k * math.pi / 6
        dx, dy = math.cos(a), math.sin(a)
        proj = (x - c) * dx + (y - c) * dy               # 沿臂投影
        perp = np.abs(-(x - c) * dy + (y - c) * dx)
        arm = np.exp(-(perp / 0.7) ** 2) * (np.abs(proj) < c - 0.5)
        alpha = np.maximum(alpha, arm)
    alpha = np.maximum(alpha, np.exp(-(radial(n, n) / 1.7) ** 2))
    save_rgba(out / "flake.png", np.ones((n, n)), np.clip(alpha * 0.95, 0, 1))


def gen_drop(out: Path) -> None:
    """玻璃水滴母版 44×56：縱橢圓透鏡——邊緣厚（亮/實）、中心薄、底緣聚光
    暗弧、左上主高光＋右下次高光。執行期縮放到各尺寸再染色。"""
    w, h = 44, 56
    y, x = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    # 橢圓歸一化半徑
    er = np.hypot((x - cx) / (w * 0.42), (y - cy) / (h * 0.44))
    body = smoothstep(1.05, 0.92, er)
    rim = smoothstep(0.55, 0.95, er) * body              # 邊緣厚
    alpha = body * (0.30 + 0.55 * rim)
    # 底緣聚光暗弧（透鏡把光折向下方 → 上亮下暗的內緣）
    bottom = smoothstep(0.55, 1.0, (y - cy) / (h * 0.44)) * body
    rgb = 0.62 + 0.30 * rim - 0.28 * bottom * rim
    # 主高光（左上，鏡面）＋次高光（右下，反射窗）
    hl = np.exp(-(radial(w, h, w * 0.34, h * 0.28) / (w * 0.10)) ** 2)
    hl2 = np.exp(-(radial(w, h, w * 0.62, h * 0.66) / (w * 0.16)) ** 2) * 0.4
    rgb = np.clip(rgb + hl * 0.9 + hl2 * 0.35, 0, 1.2)
    alpha = np.clip(alpha + hl * 0.55 + hl2 * 0.2, 0, 0.92) * body
    save_rgba(out / "drop.png", np.clip(rgb, 0, 1), alpha)


def gen_fog(out: Path) -> None:
    w, h = 620, 90
    tex = fbm(w, h, seed=21, octaves=4, base=6)
    y = np.mgrid[0:h, 0:w][0]
    envelope = np.exp(-(((y - h / 2) / (h * 0.30)) ** 2))
    # 兩端淡出
    x = np.mgrid[0:h, 0:w][1]
    ends = smoothstep(0, w * 0.18, x) * smoothstep(w, w * 0.82, x)
    alpha = envelope * ends * (0.35 + 0.65 * tex) * 0.5
    save_rgba(out / "fog.png", np.ones((h, w)), alpha)


def gen_sky(out: Path) -> None:
    """天空漸層帶 400×230：頂部實、往下線性淡出。中性白，執行期染色決定
    夜空藍/雨天灰藍/晴天暖光。"""
    w, h = 400, 230
    y = np.mgrid[0:h, 0:w][0]
    alpha = (1 - y / h) ** 1.6 * 0.55
    save_rgba(out / "sky.png", np.ones((h, w)), alpha)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    pygame.init()
    args.out.mkdir(parents=True, exist_ok=True)
    gen_cloud(args.out, "cloud_0", seed=11,
              layout=[(0.18, 0.58, 0.20), (0.41, 0.42, 0.28),
                      (0.62, 0.40, 0.26), (0.83, 0.56, 0.18)])
    gen_cloud(args.out, "cloud_1", seed=12,
              layout=[(0.16, 0.55, 0.17), (0.36, 0.44, 0.24),
                      (0.58, 0.38, 0.28), (0.80, 0.52, 0.21)])
    gen_glow(args.out)
    gen_rays(args.out)
    gen_moon(args.out)
    gen_star(args.out)
    gen_flake(args.out)
    gen_drop(args.out)
    gen_fog(args.out)
    gen_sky(args.out)


if __name__ == "__main__":
    main()
