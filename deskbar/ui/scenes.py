"""氛圍場景引擎：中欄的「非工具向」動態畫面（Wallpaper Engine 精神）。

八個場景，全部程序生成、Pi Zero 2W 量級的運算（粒子/折線/小像素面，
沒有每幀大面積 per-pixel 迴圈）；使用者在網頁勾選要輪播哪些
（settings.scenes_enabled），每次進入隨機挑一個、每 ROTATE_S 秒輪換。

- flow      流場墨線：粒子沿慢漂向量場游走拖尾（三尺度正弦≈廉價 Perlin）
- stars     星河流星：三層視差星空＋不定時流星（隨機驚喜彩蛋）
- ridges    呼吸山稜：層疊山影橫幅，色溫隨晝夜走，雲影飄過
- fireflies 螢火蟲夜原：下半部暖光點呼吸明滅
- fish      水墨游魚：三尾魚影群游，天氣差游得深（畫面即資訊）
- aurora    極光：緞帶光幕波動＋垂簾
- train     像素電車窗景：車窗外田野電桿城市視差流過（動漫感，4x 像素）
- runner    像素小冒險者：8-bit 小人橫向卷軸奔跑跳障礙（瑪利歐精神，自製素材）

節奏鐵則同 weatherfx：t 是呼叫端傳入的單調浮點秒；每天以日序摻種子，
今天的星空/山稜/世界全世界只有這一幅。點場景任意處＝scene_tap（app 依
scene_mode 決定回行事曆後要不要 60 秒後強制回來）。
"""

from __future__ import annotations

import math

import pygame

from deskbar.config import SCENE_KEYS
from deskbar.layout import Rect
from deskbar.ui import Hit, theme

# 中欄場景區：x 避開左欄(400)與右欄(1520)，y 讓出頂緣日光帶(8px)
AREA = Rect(402, 8, 1118, 472)
FPS = 10                     # 場景氛圍幀率（app 的 ambient 分支用）
ROTATE_S = 600               # 同場景最長停留（到點換下一個隨機場景）
_PX = 4                      # 像素場景的放大倍率（nearest-neighbor 出格子感）


def new_state() -> dict:
    return {"kind": None, "kind_at": -1e9, "t_last": None, "data": {}}


def _h(*args) -> float:
    """黃金比例雜湊 → [0,1)（同 weatherfx：位置/速度/相位全走這裡）。"""
    x = 0x9E3779B9
    for a in args:
        x = (x ^ (int(a) & 0xFFFFFFFF)) * 2654435761 & 0xFFFFFFFF
        x ^= x >> 15
    return ((x * 2246822519 & 0xFFFFFFFF) >> 8) / float(1 << 24)


def _lerp(a, b, p: float) -> tuple:
    p = max(0.0, min(1.0, p))
    return tuple(round(a[i] + (b[i] - a[i]) * p) for i in range(3))


def _mix(color, alpha: int) -> tuple:
    """以 alpha/255 朝主題背景 lerp（平坦背景上等價於 alpha 合成）。"""
    return _lerp(theme.C["bg"], color, alpha / 255.0)


def _day_seed(now) -> int:
    return now.year * 400 + now.timetuple().tm_yday


def _hour_ramp(now, night, dawn, day, dusk) -> tuple:
    """粗略晝夜色錨點（05-07 晨、07-16.5 晝、16.5-19 昏、其餘夜）平滑內插。
    場景用近似即可——分鐘級精準日出日落屬於日光儀。"""
    h = now.hour + now.minute / 60.0
    for lo, hi, ca, cb in ((5.0, 7.0, night, dawn), (7.0, 8.5, dawn, day),
                           (16.5, 18.0, day, dusk), (18.0, 20.0, dusk, night)):
        if lo <= h < hi:
            return _lerp(ca, cb, (h - lo) / (hi - lo))
    return day if 8.5 <= h < 16.5 else night


# ---------------------------------------------------------------- flow 流場墨線

def _flow_init(d: dict, seed: int, w: int, h: int) -> None:
    d["trail"] = pygame.Surface((w, h), pygame.SRCALPHA)
    d["parts"] = [[_h(i, seed) * w, _h(i, seed, 7) * h, _h(i, seed, 3)]
                  for i in range(90)]


def _flow(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    if "trail" not in d:
        _flow_init(d, seed, w, h)
    d["trail"].fill((0, 0, 0, 5), special_flags=pygame.BLEND_RGBA_SUB)
    if theme.current_theme() == "light":
        c0, c1 = _hour_ramp(now, (90, 100, 150), (190, 120, 60),
                            (70, 110, 150), (190, 120, 60)), (150, 120, 80)
    else:
        c0, c1 = _hour_ramp(now, (100, 120, 210), (220, 140, 70),
                            (96, 156, 190), (220, 140, 70)), (170, 150, 100)
    phase = (seed % 97) * 0.13
    for i, p in enumerate(d["parts"]):
        ang = 2.1 * (math.sin(p[0] * 0.0021 + t * 0.031 + phase)
                     + math.cos(p[1] * 0.0034 - t * 0.023 + phase * 1.7)
                     + math.sin((p[0] + p[1]) * 0.0012 + t * 0.017))
        spd = 26 + p[2] * 34
        nx, ny = p[0] + math.cos(ang) * spd * dt, p[1] + math.sin(ang) * spd * dt
        if 0 <= nx < w and 0 <= ny < h:
            pygame.draw.line(d["trail"], (*_lerp(c0, c1, p[2]), 200),
                             (p[0], p[1]), (nx, ny), 2)
            p[0], p[1] = nx, ny
        else:
            cell = int(t * 3) + i
            p[0], p[1] = _h(cell, seed, 11) * w, _h(cell, seed, 12) * h
    panel.fill(theme.C["bg"])
    panel.blit(d["trail"], (0, 0))


# ---------------------------------------------------------------- stars 星河流星

def _stars(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    panel.fill(theme.C["bg"])
    dark = theme.current_theme() == "dark"
    base = (225, 230, 245) if dark else (110, 116, 142)
    for li, (n, spd, r, a0) in enumerate(((14, 1.6, 1, 90), (16, 3.2, 1, 140),
                                          (18, 6.0, 2, 205))):
        for i in range(n):
            x = (_h(li, i, seed) * w - t * spd) % w
            y = _h(li, i, seed, 2) * (h - 20) + 10
            tw = math.sin(t * (0.5 + _h(li, i, 3) * 1.4) + _h(li, i, 4) * 6.28)
            a = a0 + int(50 * tw)
            if a > 20:
                pygame.draw.circle(panel, _mix(base, a), (round(x), round(y)), r)
    # 流星：每 35–80 秒一顆（雜湊排程），0.7 秒劃過，尾巴漸淡
    cyc = int(t // 40)
    launch = cyc * 40 + _h(cyc, seed, 9) * 38
    age = t - launch
    if 0.0 <= age <= 0.7 and _h(cyc, seed, 8) > 0.35:
        p = age / 0.7
        x0, y0 = _h(cyc, 5) * w * 0.8 + w * 0.1, _h(cyc, 6) * h * 0.3 + 8
        dx, dy = 260.0, 120.0
        hx, hy = x0 + dx * p, y0 + dy * p
        for k in range(5):                      # 5 段尾巴，越後越淡
            q = max(0.0, p - k * 0.05)
            a = int((235 if dark else 190) * (1 - p) * (1 - k / 5))
            pygame.draw.line(panel, _mix((255, 240, 210) if dark
                                         else (150, 120, 60), a),
                             (x0 + dx * q, y0 + dy * q),
                             (x0 + dx * max(0.0, q - 0.05),
                              y0 + dy * max(0.0, q - 0.05)), 2)
        pygame.draw.circle(panel, _mix((255, 250, 235), int(255 * (1 - p))),
                           (round(hx), round(hy)), 2)


# ---------------------------------------------------------------- ridges 呼吸山稜

_RIDGE_PAL = {          # (夜, 晨, 晝, 昏) × 三層由遠到近——山永遠是藍紫系，
    "dark": (((52, 60, 96), (148, 120, 150), (110, 130, 156), (160, 110, 130)),
             ((38, 44, 74), (108, 88, 124), (84, 102, 128), (112, 80, 108)),
             ((26, 30, 52), (70, 56, 90), (60, 74, 98), (72, 52, 82))),
    "light": (((176, 182, 202), (222, 186, 176), (168, 186, 206), (216, 176, 168)),
              ((150, 158, 184), (196, 156, 158), (140, 160, 186), (190, 148, 152)),
              ((122, 132, 162), (166, 126, 138), (112, 134, 164), (158, 120, 136))),
}       # 暖色只出現在晨昏的「遠山染霞」，近山始終沉穩（第一版全層轉棕＝土丘）


def _ridge_y(x: float, li: int, seed: int, w: int, h: int, t: float) -> float:
    base = h * (0.52 + 0.16 * li)
    amp = h * (0.10 + 0.05 * li)
    s = seed + li * 31
    y = base \
        + amp * math.sin(x * 0.006 + _h(s, 1) * 6.28) * 0.6 \
        + amp * math.sin(x * 0.017 + _h(s, 2) * 6.28) * 0.3 \
        + amp * math.sin(x * 0.041 + _h(s, 3) * 6.28) * 0.12 \
        + math.sin(t * 0.05 + li) * 2.0          # 極慢的「呼吸」起伏
    return y


def _ridges(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    pal = _RIDGE_PAL[theme.current_theme()]
    sky = _hour_ramp(now, *([_lerp(pal[0][i], theme.C["bg"], 0.55)
                             for i in range(4)]))
    panel.fill(_lerp(theme.C["bg"], sky, 0.5))
    for li in range(3):
        col = _hour_ramp(now, *pal[li])
        pts = [(x, _ridge_y(x, li, seed, w, h, t)) for x in range(0, w + 16, 16)]
        pygame.draw.polygon(panel, col, pts + [(w, h), (0, h)])
    # 雲影：兩團暗斑貼著近山飄
    shade = pygame.Surface((260, 90), pygame.SRCALPHA)
    pygame.draw.ellipse(shade, (0, 0, 0, 42), shade.get_rect())
    for i in range(2):
        cx = (t * (7 + i * 4) + _h(i, seed) * w) % (w + 260) - 260
        panel.blit(shade, (round(cx), round(h * 0.62 + i * 40)))


# ---------------------------------------------------------------- fireflies 螢火蟲

def _fireflies(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    panel.fill(theme.C["bg"])
    if "glow" not in d:
        g = pygame.Surface((26, 26), pygame.SRCALPHA)
        for r, a in ((13, 26), (9, 54), (5, 110), (2, 220)):
            pygame.draw.circle(g, (188, 226, 120, a), (13, 13), r)
        d["glow"] = g
    # 草叢暗帶（底部漸深，光點才有著落）
    for i in range(4):
        band = pygame.Rect(0, h - 46 + i * 12, w, 12)
        panel.fill(_lerp(theme.C["bg"], (0, 0, 0), 0.10 + i * 0.05), band)
    dark = theme.current_theme() == "dark"
    for i in range(22):
        ax = _h(i, seed) * w
        ay = h * 0.45 + _h(i, seed, 2) * h * 0.5
        x = ax + math.sin(t * (0.16 + _h(i, 3) * 0.2) + i) * 70
        y = ay + math.sin(t * (0.23 + _h(i, 4) * 0.24) + i * 2.1) * 26
        breathe = math.sin(t * (0.7 + _h(i, 5) * 1.2) + _h(i, 6) * 6.28)
        a = int(150 + 105 * breathe)
        if a < 46:
            continue                              # 熄滅期
        spr = d["glow"]
        spr.set_alpha(a if dark else int(a * 0.7))
        panel.blit(spr, (round(x) - 13, round(y) - 13))


# ---------------------------------------------------------------- fish 水墨游魚

def _fish(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    if "fish" not in d:
        d["fish"] = [{"x": _h(i, seed) * w, "y": h * 0.5,
                      "vx": 40 + _h(i, seed, 2) * 26, "trail": []}
                     for i in range(3)]
    panel.fill(theme.C["bg"])
    # 天氣決定游泳深度帶：晴淺、雨深（畫面即資訊，Livegrid 精神）
    band = 0.30 if (code or 0) <= 2 else 0.62
    ink = (208, 214, 228) if theme.current_theme() == "dark" else (52, 60, 76)
    for i, f in enumerate(d["fish"]):
        ty = h * band + math.sin(t * 0.11 + i * 2.4) * h * 0.12 \
            + i * 26 - 26                          # 各自錯開的巡游深度
        f["y"] += (ty - f["y"]) * min(1.0, dt * 0.8)
        f["x"] += f["vx"] * dt
        if f["x"] > w + 60:
            f["x"] = -60
            f["vx"] = 40 + _h(i, int(t)) * 26
        f["trail"].insert(0, (f["x"], f["y"]))
        del f["trail"][10:]
        # 水墨筆觸：頭大尾細的圓串，越尾越淡
        for k, (tx, tyy) in enumerate(f["trail"]):
            r = max(1, round(7 - k * 0.7))
            a = int(210 * (1 - k / 10))
            pygame.draw.circle(panel, _mix(ink, a), (round(tx), round(tyy)), r)
        # 尾鰭一撇
        if len(f["trail"]) >= 2:
            hx, hy = f["trail"][0]
            pygame.draw.line(panel, _mix(ink, 120),
                             (hx - 16, hy), (hx - 24, hy - 5), 2)
            pygame.draw.line(panel, _mix(ink, 120),
                             (hx - 16, hy), (hx - 24, hy + 5), 2)


# ---------------------------------------------------------------- aurora 極光

def _aurora(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    panel.fill(theme.C["bg"])
    dark = theme.current_theme() == "dark"
    ribbons = (((70, 220, 170), 0.24), ((120, 150, 235), 0.34),
               ((190, 110, 210), 0.30))
    for ri, (col, base) in enumerate(ribbons):
        if not dark:
            col = _lerp(col, (110, 120, 140), 0.45)
        pts = []
        for x in range(0, w + 20, 20):
            y = h * base + math.sin(x * 0.004 + t * 0.16 + ri * 2.1) * 34 \
                + math.sin(x * 0.011 - t * 0.09 + ri) * 18
            pts.append((x, y))
        # 垂簾：細而密、深淺不齊的光柱（8px 粗齒是第一版的雲霄飛車感元凶）
        for x in range(0, w, 7):
            k = min(len(pts) - 1, x // 20)
            y = pts[k][1] + (pts[min(k + 1, len(pts) - 1)][1] - pts[k][1]) \
                * (x % 20) / 20.0
            depth = 30 + _h(ri, x, seed) * 90
            sway = math.sin(t * 0.5 + x * 0.05 + ri) * 0.5 + 0.5
            pygame.draw.line(panel, _mix(col, int(30 + 44 * sway)),
                             (x, y), (x, y + depth), 3)
        for off, wd, a in ((-4, 9, 40), (0, 5, 120), (2, 3, 190)):
            pygame.draw.lines(panel, _mix(col, a), False,
                              [(x, y + off) for x, y in pts], wd)


# ---------------------------------------------------------------- 像素場景共用

def _pxsurf(d: dict, w: int, h: int) -> "pygame.Surface":
    pw, ph = w // _PX, h // _PX
    s = d.get("px")
    if s is None or s.get_size() != (pw, ph):
        s = pygame.Surface((pw, ph))
        d["px"] = s
    return s


_SKY_STOPS = {"night": (16, 20, 44), "dawn": (232, 150, 96),
              "day": (120, 170, 220), "dusk": (226, 120, 84)}


def _px_sky(ps, now) -> None:
    """像素天空：晝夜色帶垂直漸層（頂深底亮的三段近似）。"""
    pw, ph = ps.get_size()
    top = _hour_ramp(now, *(_SKY_STOPS[k] for k in ("night", "dawn", "day",
                                                    "dusk")))
    bot = _lerp(top, (255, 244, 214), 0.35)
    for i in range(3):
        ps.fill(_lerp(top, bot, i / 2), pygame.Rect(0, ph * i // 3, pw,
                                                    ph // 3 + 1))


# ---------------------------------------------------------------- train 電車窗景

def _train(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    ps = _pxsurf(d, w, h)
    pw, ph = ps.get_size()
    _px_sky(ps, now)
    horizon = int(ph * 0.58)
    night = not (6 <= now.hour < 19)
    # 遠景：城市/丘陵剪影（極慢），雜湊天際線
    far = _lerp(_SKY_STOPS["night"], (90, 100, 130), 0.4) if night \
        else (96, 112, 138)
    off1 = int(t * 3)
    for bx in range(-1, pw // 12 + 2):
        cell = bx + off1 // 12
        bh = int(_h(cell, seed, 1) * 14) + 4
        ps.fill(far, pygame.Rect(bx * 12 - off1 % 12, horizon - bh, 11, bh))
    # 中景：田野色帶（中速）
    field_day = ((124, 168, 92), (106, 152, 84), (166, 150, 96))
    field_night = ((44, 60, 46), (38, 52, 42), (60, 56, 40))
    off2 = int(t * 14)
    for bx in range(-1, pw // 20 + 2):
        cell = bx + off2 // 20
        col = (field_night if night else field_day)[int(_h(cell, 7) * 2.99)]
        ps.fill(col, pygame.Rect(bx * 20 - off2 % 20, horizon, 20, ph - horizon))
    ps.fill(_lerp(far, (0, 0, 0), 0.25), pygame.Rect(0, horizon, pw, 1))
    # 近景：電線桿（快速掃過）＋兩條電車線微垂
    pole = (30, 30, 34) if not night else (14, 14, 18)
    spacing = 64
    off3 = int(t * 60)
    for bx in range(-1, pw // spacing + 2):
        x = bx * spacing - off3 % spacing
        ps.fill(pole, pygame.Rect(x, 4, 2, ph - 10))
        ps.fill(pole, pygame.Rect(x - 5, 7, 12, 2))
    for wy, amp in ((9, 3), (13, 2)):
        for x in range(0, pw, 4):
            sag = math.sin((x + off3 % spacing) / spacing * math.pi)
            ps.set_at((x, wy + int(abs(sag) * amp)), pole)
    panel.blit(pygame.transform.scale(ps, (pw * _PX, ph * _PX)), (0, 0))


# ---------------------------------------------------------------- runner 小冒險者

_RUN_FRAMES = (      # 10×12 像素小人（自製，非任何 IP）：跑步兩幀
    ("   tttt   ", "   tttt   ", "   ffff   ", "   ffff   ", " ssssssss ",
     "s sssssss ", "  ssssss  ", "  pppppp  ", "  pp  pp  ", "  pp   pp ",
     " bb     bb", "bb        "),
    ("   tttt   ", "   tttt   ", "   ffff   ", "   ffff   ", " ssssssss ",
     " sssssss s", "  ssssss  ", "  pppppp  ", "   pppp   ", "   pppp   ",
     "  bbbb    ", "    bbbb  "),
)
_RUN_PAL = {"t": (60, 140, 130), "f": (232, 190, 150), "s": (70, 150, 140),
            "p": (110, 84, 60), "b": (52, 40, 32)}


def _runner(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    ps = _pxsurf(d, w, h)
    pw, ph = ps.get_size()
    _px_sky(ps, now)
    ground = ph - 16
    night = not (6 <= now.hour < 19)
    gcol = (52, 92, 60) if not night else (30, 44, 34)
    ps.fill(gcol, pygame.Rect(0, ground, pw, 16))
    ps.fill(_lerp(gcol, (0, 0, 0), 0.3), pygame.Rect(0, ground, pw, 1))
    # 雲（像素塊，極慢）
    for i in range(3):
        cx = (_h(i, seed) * pw - t * 2) % (pw + 30) - 15
        cy = 6 + _h(i, seed, 2) * 16
        cc = (210, 218, 232) if not night else (60, 66, 92)
        ps.fill(cc, pygame.Rect(int(cx), int(cy), 16, 4))
        ps.fill(cc, pygame.Rect(int(cx) + 3, int(cy) - 3, 10, 3))
    # 障礙物世界（60px/s 卷軸）：每 48px 一格，雜湊決定有無石塊
    scroll = t * 60
    off = int(scroll)
    runner_px = 40
    jump = 0.0
    for cell in range(off // 48 - 1, (off + pw) // 48 + 2):
        if _h(cell, seed, 5) > 0.62:
            x = cell * 48 - off
            bh = 6 + int(_h(cell, seed, 6) * 5)
            ps.fill((104, 96, 88) if not night else (58, 54, 50),
                    pygame.Rect(x, ground - bh, 8, bh))
            # 前方 22px 內有障礙 → 起跳（拋物線 0.55 秒）
            dist = x - runner_px
            if -6 <= dist <= 26:
                p = 1 - abs(dist - 10) / 16.0
                jump = max(jump, max(0.0, p) * 15)
    frame = _RUN_FRAMES[int(t * 6) % 2 if jump < 2 else 0]
    ry = ground - 12 - jump
    for yy, row in enumerate(frame):
        for xx, ch in enumerate(row):
            if ch != " ":
                ps.set_at((runner_px + xx, int(ry) + yy), _RUN_PAL[ch])
    panel.blit(pygame.transform.scale(ps, (pw * _PX, ph * _PX)), (0, 0))


# ---------------------------------------------------------------- ink 墨滴暈染

def _ink(panel, d, now, t, dt, code, seed) -> None:
    w, h = panel.get_size()
    panel.fill(theme.C["bg"])
    ink = (216, 220, 232) if theme.current_theme() == "dark" else (44, 50, 66)
    LIFE, EVERY = 18.0, 6.0
    for k in range(6):                      # 最多 6 滴同時在生命週期內
        born = (int(t // EVERY) - k) * EVERY + _h(k, seed) * 3
        age = t - born
        if not 0.0 <= age <= LIFE:
            continue
        i = int(born)
        x = _h(i, seed, 1) * (w - 160) + 80
        y = _h(i, seed, 2) * (h - 160) + 80
        r = (60 + _h(i, seed, 3) * 60) * (1 - math.exp(-age / 3.5))
        fade = min(age / 1.5, (LIFE - age) / 6.0, 1.0)
        for rr, a in ((r, 70), (r * 0.72, 95), (r * 0.45, 130)):
            pygame.draw.circle(panel, _mix(ink, int(a * fade)),
                               (round(x), round(y)), round(rr))
        pygame.draw.circle(panel, _mix(ink, int(185 * fade)),
                           (round(x), round(y)), round(r), 2)


# ---------------------------------------------------------------- 調度

_SCENES = {"flow": _flow, "stars": _stars, "ridges": _ridges,
           "fireflies": _fireflies, "fish": _fish, "aurora": _aurora,
           "train": _train, "runner": _runner, "ink": _ink}
assert set(_SCENES) == set(SCENE_KEYS), "registry 必須與 config.SCENE_KEYS 同步"


def render(surface, ui: dict, now, t: float, enabled=None,
           weather_code=None) -> list:
    """畫一幀到 AREA；enabled＝settings.scenes_enabled（None＝全部）。
    進入時/輪換時從 enabled 隨機挑（種子摻日序與時刻，同天不同次不同款）。
    回傳 hits：整區一個 scene_tap（app 依 scene_mode 決定行為）。"""
    enabled = [k for k in (enabled if enabled else SCENE_KEYS) if k in _SCENES] \
        or list(SCENE_KEYS)
    if ui["kind"] not in enabled or t - ui["kind_at"] > ROTATE_S:
        salt = int(t) // max(1, int(ROTATE_S))
        pick = enabled[int(_h(_day_seed(now), salt, int(t * 991)) * len(enabled))]
        if pick != ui["kind"] or t - ui["kind_at"] > ROTATE_S:
            ui.update(kind=pick, kind_at=t, data={}, t_last=None)
    dt = 1.0 / FPS if ui["t_last"] is None else max(0.0, min(0.25, t - ui["t_last"]))
    ui["t_last"] = t
    rect = pygame.Rect(int(AREA.x), int(AREA.y), int(AREA.w), int(AREA.h))
    panel = surface.subsurface(rect.clip(surface.get_rect()))
    _SCENES[ui["kind"]](panel, ui["data"], now, t, dt, weather_code,
                        _day_seed(now))
    return [Hit(Rect(AREA.x, AREA.y, AREA.w, AREA.h), "scene_tap", None)]
