"""左面板天氣場景層——HTC Sense 風格的動態天氣（2026-07-27 三版：烘焙素材）。

三版架構（「程式員美術天花板」的最終解）：pygame 圓/線畫出來的場景永遠是
貼紙感，真實感來自材質。所有柔邊/漸層/噪聲類元素改用 tools/gen_weather_assets.py
離線烘焙的中性白 PNG（fBm 絮狀雲、高斯光暈、錐形光芒、隕坑月面、透鏡水滴、
霧帶、天空漸層），執行期只做「載入→依主題染色→blit」——Pi Zero 2W 上比逐幀
畫幾何更便宜。線條類（雨絲、閃電、雨刷、濺落）保留向量，銳利感是它們的本色。

兩層結構，忠於 HTC Sense 的玻璃比喻（雨刷/雪花貼螢幕是它的招牌）：
- draw()：背景場景，畫在時鐘/文字「之前」——天空漸層打底，然後太陽光芒旋轉
  ＋光暈呼吸、夜晚月亮星星、多雲視差、分景深雨絲＋濺落、雷雨閃電、雪、霧帶。
- draw_glass()：玻璃前景，畫在整個左欄內容「之後」（蓋在時鐘上）——雨天
  水滴積聚在玻璃上、每 WIPE_PERIOD_S 秒雨刷去回掃一趟抹掉水滴；雪天雪花
  黏附玻璃、漸融消失。只有雨/雷/雪族群有玻璃層，其餘 code 不畫。

座標一律透過 surface.subsurface() 裁切在 (x0, 0)-(x0+w, h) 內，任何座標
算錯也畫不出這個矩形。

節奏鐵則：t 是「浮點秒數」，由呼叫端用單調時鐘算好傳入（app._weather_t()）；
本模組是 (code, t, night) 的純函式，不得讀 pygame.time / time.time() 自行
計時——同一組參數永遠畫出同一張圖，測試與 filmstrip 工具都靠這個性質。
速度單位全部是「px/秒」。

寫實化鐵則（二版檢討，仍然成立）：位置/大小/相位一律走 _h() 黃金比例雜湊
（線性同餘會排出等距斜格）；雨絲每落完一輪重抽 x；SRCALPHA 上 draw 是覆寫
不是混合。

快取鐵則：_raw 快取原始素材（與主題無關、檔案固定集合）；_sprites 快取
「染色×尺寸」變體，key 全部來自固定組合（素材名×調色盤色×固定尺寸表×主題），
物理上封頂；主題切換透過 theme.register_cache_clear 清 _sprites（_raw 不必清）。
set_alpha 是「每次 blit 前都要設」的易變狀態，一律走 _blit() 包裝。
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame

from deskbar.ui import theme

CLEAR_CODES = {0}
CLOUD_CODES = {1, 2, 3}
FOG_CODES = {45, 48}
RAIN_CODES = set(range(51, 68)) | {80, 81, 82}
SNOW_CODES = set(range(71, 78)) | {85, 86}
THUNDER_CODES = set(range(95, 100))
# app.py 的氛圍重繪分支用這個集合當防禦閘門：open-meteo 正常會回的 code 其實
# 全部在裡面（這不是省電機制，是對「未知 code／沒天氣資料」的保險），真正的
# 省電槓桿是 ambient_fps() 的分級幀率。
ANIMATED_CODES = (CLEAR_CODES | CLOUD_CODES | FOG_CODES | RAIN_CODES
                  | SNOW_CODES | THUNDER_CODES)


def ambient_fps(code: int) -> int:
    """氛圍幀的分級幀率：動得快的場景才配高幀率（見 ANIMATED_CODES 註解）。"""
    if code in RAIN_CODES or code in THUNDER_CODES:
        return 15
    if code in SNOW_CODES:
        return 12
    return 8      # 晴/雲/霧：慢場景，8fps 已無可見差異


_HEAVY_RAIN_CODES = {63, 65, 66, 67, 81, 82} | THUNDER_CODES
_DRIZZLE_CODES = set(range(51, 58))
GLASS_CODES = RAIN_CODES | THUNDER_CODES | SNOW_CODES   # 有玻璃前景層的族群

FLASH_PERIOD_S = 6.5          # 雷雨閃電週期；strobe 兩段見 _draw_lightning
_SUN_RAY_DEG_PER_S = 9.0      # 光芒旋轉速率（HTC 的太陽轉得很慢、很沉）
WIPE_PERIOD_S = 14.0          # 玻璃雨滴的完整循環：積聚→雨刷去回→乾淨
_WIPE_START = 10.0            # 循環內第幾秒開始刷（前面都在積水滴）
_WIPE_SWEEP_S = 1.2           # 雨刷單程秒數（去程＋回程共兩倍）
# 雨刷支點在面板「右下角外側」、膠條沿臂徑向——真車構型。第一版支點放底緣
# 正中、膠條垂直臂，結果掃到 0 度是一根貫穿全高的直桿切過時鐘冒號（審查：像
# scrollbar 故障）、修成 T 型後刀頭又在大角度時整支飛出面板外。角落支點讓
# 任何掃角看起來都是「斜掃過擋風玻璃」的經典構圖。
_WIPE_FROM_DEG = -100.0       # 停放角：臂貼在面板底緣之下（畫面外）
_WIPE_TO_DEG = -2.0           # 掃到頂：蓋過面板內所有水滴的角度（右上角 φ≈-4.3°）
_DROP_N = 26                  # 玻璃水滴數量上限（一個循環內全部生出來）

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "weatherfx"
ASSET_NAMES = ("cloud_0", "cloud_1", "glow", "rays", "moon", "star", "flare",
               "flake", "drop", "fog", "sky")

_raw_cache: dict = {}         # 原始素材（中性白，主題無關）——最多 len(ASSET_NAMES) 張
_sprites: dict = {}           # 染色×尺寸變體——key 組合固定封頂，主題切換清空
build_count = 0


def _clear_cache() -> None:
    _sprites.clear()


theme.register_cache_clear(_clear_cache)


def _raw(name: str) -> "pygame.Surface":
    s = _raw_cache.get(name)
    if s is None:
        s = pygame.image.load(str(_ASSET_DIR / f"{name}.png"))
        _raw_cache[name] = s
    return s


def _sprite(name: str, color, size=None) -> "pygame.Surface":
    """素材的「染色×尺寸」變體（乘法染色保留烘焙的明暗/高光）。"""
    global build_count
    key = (name, color, size, theme.current_theme())
    s = _sprites.get(key)
    if s is None:
        build_count += 1
        s = _raw(name)
        s = pygame.transform.smoothscale(s, size) if size else s.copy()
        s.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        _sprites[key] = s
    return s


def _blit(panel, spr: "pygame.Surface", pos, alpha: int = 255) -> None:
    """set_alpha 是殘留狀態：快取的 sprite 上一次 blit 設過的值會留著，
    所以每次 blit 都必須顯式設定（255 也要設）。"""
    spr.set_alpha(max(0, min(255, alpha)))
    panel.blit(spr, pos)


def _h(*args) -> float:
    """確定性偽隨機（黃金比例整數雜湊 → [0,1)）：位置/大小/相位全走這裡，
    避免線性同餘的等距格狀分佈（寫實化鐵則第一條）。"""
    x = 0x9E3779B9
    for a in args:
        x = (x ^ (int(a) & 0xFFFFFFFF)) * 2654435761 & 0xFFFFFFFF
        x ^= x >> 15
    return ((x * 2246822519 & 0xFFFFFFFF) >> 8) / float(1 << 24)


def _pal() -> dict:
    """依當前主題回傳場景配色（已過 theme.col() 的 BGR 校正）。淺色主題的雲/雨
    /雪改用偏深的灰藍——原本深色主題的亮色系在米白背景上會直接隱形。"""
    if theme.current_theme() == "light":
        return {
            "rain": theme.col((96, 122, 168)), "cloud": theme.col((132, 138, 152)),
            "sun": theme.col((238, 152, 42)), "ray": theme.col((236, 158, 52)),
            "glow": theme.col((240, 176, 84)), "star": theme.col((112, 116, 142)),
            "moon": theme.col((150, 154, 172)), "snow": theme.col((132, 142, 164)),
            "mist": theme.col((160, 164, 176)), "bolt": theme.col((222, 158, 30)),
            "splash": theme.col((120, 144, 184)),
            "drop": theme.col((150, 168, 205)),
            "wiper": theme.col((88, 90, 96)), "wiper_edge": theme.col((140, 142, 148)),
        }
    return {
        "rain": theme.col((120, 150, 190)), "cloud": theme.col((205, 212, 226)),
        "sun": theme.col((255, 191, 82)), "ray": theme.col((255, 178, 72)),
        "glow": theme.col((255, 202, 112)), "star": theme.col((235, 238, 248)),
        "moon": theme.col((232, 232, 220)), "snow": theme.col((234, 240, 250)),
        "mist": theme.col((198, 204, 214)), "bolt": theme.col((255, 238, 176)),
        "splash": theme.col((150, 180, 216)),
        "drop": theme.col((188, 212, 242)),
        "wiper": theme.col((105, 110, 118)), "wiper_edge": theme.col((182, 187, 194)),
    }


# 天空漸層帶（sky.png 染色）：family → (色, 深色主題 alpha, 淺色主題 alpha)。
# 淺色主題底是米白，同 alpha 會過搶，砍到約 6 成。
_SKY = {
    "clear_day": ((255, 196, 110), 58, 34),
    "night": ((86, 110, 200), 110, 56),
    "cloud": ((176, 184, 202), 64, 38),
    "fog": ((176, 180, 190), 86, 50),
    "rain": ((108, 134, 182), 96, 54),
    "thunder": ((114, 126, 190), 110, 62),
    "snow": ((176, 190, 214), 86, 50),
}


def _mix(color, alpha: int):
    """把 color 以 alpha/255 的比例朝主題背景色 lerp——在平坦背景上等價於
    alpha 合成，但可以直接用 pygame.draw.line/circle 畫實色。"""
    a = max(0, min(255, alpha)) / 255.0
    bg = theme.C["bg"]
    return tuple(round(bg[i] + (color[i] - bg[i]) * a) for i in range(3))


def _draw_sky(panel, family: str, w: int) -> None:
    color, a_dark, a_light = _SKY[family]
    alpha = a_light if theme.current_theme() == "light" else a_dark
    _blit(panel, _sprite("sky", theme.col(color), (w, 230)), (0, 0), alpha)


def draw(surface, code: int, t: float, x0: int = 0, w: int = 400, h: int = 480,
         night: bool = False) -> None:
    """在 surface 的 (x0, 0)-(x0+w, h) 矩形內畫出 code 對應的天氣場景。

    t＝浮點秒數（見模組 docstring 的節奏鐵則）；night 由呼叫端依當下時刻判定，
    影響晴/多雲場景（太陽↔月亮星空）與天空色。code 對不到任何場景就完全不畫。
    """
    if w <= 0 or h <= 0:
        return
    rect = pygame.Rect(x0, 0, w, h).clip(surface.get_rect())
    if rect.width <= 0 or rect.height <= 0:
        return
    panel = surface.subsurface(rect)
    pal = _pal()
    if code in THUNDER_CODES:
        _draw_sky(panel, "thunder", w)
        _draw_rain(panel, t, w, h, pal, code)
        _draw_lightning(panel, t, w, h, pal)
    elif code in RAIN_CODES:
        _draw_sky(panel, "rain", w)
        _draw_rain(panel, t, w, h, pal, code)
    elif code in SNOW_CODES:
        _draw_sky(panel, "snow", w)
        _draw_snow(panel, t, w, h, pal)
    elif code in FOG_CODES:
        _draw_sky(panel, "fog", w)
        _draw_fog(panel, t, w, h, pal)
    elif code in CLOUD_CODES:
        _draw_sky(panel, "night" if night else "cloud", w)
        if night:
            if code == 1:
                _draw_stars(panel, t, w, h, pal, n=8)
                _draw_moon(panel, w, pal)
        elif code in (1, 2):
            _draw_sun(panel, t, w, pal, minor=(code == 2))
        _draw_clouds(panel, code, t, w, h, pal)
    elif code in CLEAR_CODES:
        _draw_sky(panel, "night" if night else "clear_day", w)
        if night:
            _draw_stars(panel, t, w, h, pal, n=14)
            _draw_moon(panel, w, pal)
        else:
            _draw_sun(panel, t, w, pal)
    # 其餘 code：刻意不畫任何東西，維持背景原樣。


def draw_glass(surface, code: int, t: float, x0: int = 0, w: int = 400,
               h: int = 480) -> None:
    """玻璃前景層：呼叫端在畫完左欄「全部內容」之後呼叫（水滴/雪花/雨刷蓋在
    時鐘與文字上——HTC Sense 的螢幕就是一片擋風玻璃）。只有 GLASS_CODES 有
    這一層；t 與 draw() 用同一個時間軸。"""
    if w <= 0 or h <= 0 or code not in GLASS_CODES:
        return
    rect = pygame.Rect(x0, 0, w, h).clip(surface.get_rect())
    if rect.width <= 0 or rect.height <= 0:
        return
    panel = surface.subsurface(rect)
    pal = _pal()
    if code in SNOW_CODES:
        _draw_glass_snow(panel, t, w, h, pal)
    else:
        _draw_glass_rain(panel, t, w, h, pal)


# ---------------------------------------------------------------- 晴：太陽/夜空

def _sun_center(w: int) -> tuple:
    # 面板右上角、時鐘卡右緣後方——太陽從時鐘後面探出來是 HTC Sense 的招牌構圖。
    return (w - 52, 38)


def _draw_sun(panel, t: float, w: int, pal: dict, minor: bool = False) -> None:
    cx, cy = _sun_center(w)
    scale = 0.72 if minor else 1.0
    # 光芒 sprite（烘焙錐形，12 道 30° 對稱）整張旋轉；轉角取 mod 30° 讓同相位
    # 逐位元一致。光芒要「長」——時鐘卡會蓋掉太陽本體的下半，靠伸出卡片邊緣的
    # 長光芒才看得出後面有顆太陽在轉。
    # 300px/alpha 190：太陽本體大半躲在時鐘卡後，存在感全靠伸出卡緣的光芒
    # ——250/150 在實機玻璃反光下幾乎看不見（驗收：「晴天沒有效果」）。
    size = int(300 * scale)
    rays = _sprite("rays", pal["ray"], (size, size))
    ang = -(t * _SUN_RAY_DEG_PER_S) % 30.0
    rot = pygame.transform.rotate(rays, ang)
    rot.set_alpha(190 if not minor else 130)
    panel.blit(rot, (cx - rot.get_width() / 2, cy - rot.get_height() / 2))
    # 呼吸光暈（外圈 alpha 呼吸，內圈穩定），最後實心日核。
    breathe = int(24 * math.sin(t * 0.55))
    g_out = int(190 * scale)
    g_in = int(104 * scale)
    _blit(panel, _sprite("glow", pal["glow"], (g_out, g_out)),
          (cx - g_out / 2, cy - g_out / 2), 132 + breathe)
    _blit(panel, _sprite("glow", pal["glow"], (g_in, g_in)),
          (cx - g_in / 2, cy - g_in / 2), 168)
    pygame.draw.circle(panel, _mix(pal["sun"], 235 if not minor else 170),
                       (cx, cy), int(19 * scale))


def _draw_moon(panel, w: int, pal: dict) -> None:
    # 月亮不能沿用太陽的位置：太陽被時鐘卡蓋住還有長光芒撐場面，月亮沒有
    # 光芒，放 (w-52,38) 會整顆縮在末張牌卡後面、只剩一小角灰鰭。改放右上角
    # 的無牌區（牌卡右緣 x=366 之外），整顆可見，再補一圈冷色月暈。
    # (w-18,30) 會被面板右緣切掉半顆，往內收到全顆可見（與時鐘卡右上角
    # 微交疊＝太陽同款的「從時鐘後面探出來」構圖）。
    cx, cy = w - 34, 34
    g = 116
    _blit(panel, _sprite("glow", pal["moon"], (g, g)), (cx - g / 2, cy - g / 2), 84)
    moon = _sprite("moon", pal["moon"], (52, 52)).copy()
    # 弦月缺口改挖穿 alpha（SRCALPHA 上 draw 是覆寫）：舊版蓋 bg 實色圓，
    # 但這層下面是夜空漸層不是純背景——實機看是月亮旁一個黑洞。
    pygame.draw.circle(moon, (0, 0, 0, 0), (18, 20), 18)
    _blit(panel, moon, (cx - 26, cy - 26))


def _draw_stars(panel, t: float, w: int, h: int, pal: dict, n: int) -> None:
    star = _sprite("star", pal["star"])
    flare = _sprite("flare", pal["star"])
    for i in range(n):
        x = int(_h(i, 11) * (w - 10)) + 5
        y = int(_h(i, 12) * h * 0.52)
        speed = 0.8 + _h(i, 13) * 1.6          # 每顆星自己的閃爍節奏
        tw = math.sin(t * speed + _h(i, 14) * 6.28)
        alpha = int((80 + 100 * _h(i, 15)) + 88 * tw)
        if alpha <= 14:
            continue                           # 閃到最暗的那幾顆這一幀乾脆熄滅
        _blit(panel, star, (x - 4, y - 4), alpha)
        if _h(i, 16) > 0.72 and tw > 0.55:     # 亮星在最亮時刻加十字光斑
            _blit(panel, flare, (x - 9, y - 9), int(alpha * 0.9))


# ---------------------------------------------------------------- 雲/霧

# (lane y 比例, 速度 px/s, 尺寸鍵) ——三層視差：低的近、快、大。
_CLOUD_LANES = ((0.585, 10.0, "l"), (0.695, 17.0, "s"), (0.80, 25.0, "l"),
                (0.50, 6.0, "s"))
_CLOUD_SIZES = {"l": (228, 90), "s": (164, 65)}


def _draw_clouds(panel, code: int, t: float, w: int, h: int, pal: dict) -> None:
    n = {1: 2, 2: 3, 3: 4}.get(code, 3)
    alpha = 172 if code < 3 else 214           # 陰天雲更厚重（烘焙 alpha 之上再乘）
    for i in range(n):
        frac, speed, size_key = _CLOUD_LANES[i]
        pw, ph = _CLOUD_SIZES[size_key]
        blob = _sprite(f"cloud_{i % 2}", pal["cloud"], (pw, ph))
        span = w + pw + 60                     # 進出場都要完整走完整個雲寬
        cx = (t * speed + _h(i, 21) * span) % span - pw
        cy = h * frac + math.sin(t * 0.1 + i * 2.2) * 3   # 極慢的上下漂
        _blit(panel, blob, (round(cx), round(cy - ph / 2)), alpha)


def _draw_fog(panel, t: float, w: int, h: int, pal: dict) -> None:
    # 霧帶必須窄於面板寬，烘焙素材兩端本身就淡出；三條不同寬度/相位橫移＋
    # 濃度呼吸。
    sizes = ((int(w * 0.92), 66), (int(w * 0.80), 58), (int(w * 0.68), 50))
    band0 = int(h * 0.55)
    for i, (bw, bh) in enumerate(sizes):
        band = _sprite("fog", pal["mist"], (bw, bh))
        x = (w - bw) / 2 + math.sin(t * 0.22 + _h(i, 32) * 6.28) * 56
        alpha = int(150 + 40 * math.sin(t * 0.5 + i * 2.3))
        _blit(panel, band, (round(x), band0 + i * 44), alpha)


# ---------------------------------------------------------------- 雨/雷/雪

def _rain_layers(code: int):
    """(數量, 速度px/s, 絲長, alpha, 線寬) ×景深層——近層快、長、亮、粗。"""
    if code in _DRIZZLE_CODES:
        return ((7, 300, 10, 64, 1), (7, 380, 13, 96, 1))
    if code in _HEAVY_RAIN_CODES:
        return ((8, 320, 12, 84, 1), (8, 420, 17, 128, 1), (12, 520, 24, 185, 2))
    return ((8, 300, 11, 76, 1), (8, 390, 15, 115, 1), (8, 480, 20, 165, 2))


def _draw_rain(panel, t: float, w: int, h: int, pal: dict, code: int) -> None:
    splash_y = h - 48
    for li, (n, speed, slen, alpha, width) in enumerate(_rain_layers(code)):
        span = splash_y + slen * 2
        for i in range(n):
            # 每落完一輪重抽 x 與亮度（寫實化鐵則：雨不能永遠落在同幾條直線上）
            prog = t * speed + _h(i, li, 41) * span * 7
            cycle = int(prog // span)
            pos = prog % span
            x = _h(i, li, cycle) * w
            y = pos - slen
            a = int(alpha * (0.75 + 0.5 * _h(i, li, cycle, 42)))
            color = _mix(pal["rain"], a)
            pygame.draw.line(panel, color, (x, y), (x - 4, y + slen), width)
            # 近層雨滴落地：濺落圈由小放大淡出＋兩顆彈起的小水珠。
            if li == 2 and pos > span - 30:
                s = (pos - (span - 30)) / 30
                rw, rh = int(5 + 15 * s), int(2 + 4 * s)
                c = _mix(pal["splash"], int(130 * (1 - s)))
                lx = x - 4
                pygame.draw.ellipse(panel, c,
                                    pygame.Rect(round(lx - rw), splash_y - rh,
                                                rw * 2, rh * 2), 1)
                bounce_y = splash_y - 14 * s * (1 - s) * 4
                for side in (-1, 1):
                    pygame.draw.circle(panel, c,
                                       (round(lx + side * (3 + 9 * s)),
                                        round(bounce_y)), 1)


def _draw_lightning(panel, t: float, w: int, h: int, pal: dict) -> None:
    tc = t % FLASH_PERIOD_S
    strobe = 0.0
    if tc < 0.12:
        strobe = 1.0
    elif 0.20 <= tc < 0.32:
        strobe = 0.6
    if strobe <= 0.0:
        return
    cycle = int(t // FLASH_PERIOD_S)
    # 每輪雜湊一條 6 段鋸齒主幹＋一條 2 段分枝；三層線寬畫出輝光。
    x = 40 + _h(cycle, 51) * (w - 120)
    y = h * 0.20
    pts = [(x, y)]
    for k in range(6):
        x += (_h(cycle, 52, k) - 0.5) * 52
        y += h * (0.07 + 0.04 * _h(cycle, 53, k))
        pts.append((x, y))
    branch_root = pts[2]
    bx, by = branch_root
    branch = [branch_root]
    for k in range(2):
        bx += (0.3 + _h(cycle, 54, k)) * 34
        by += h * (0.05 + 0.05 * _h(cycle, 55, k))
        branch.append((bx, by))
    for base_w, a in ((7, 60), (4, 120), (2, 235)):
        pygame.draw.lines(panel, _mix(pal["bolt"], int(a * strobe)), False,
                          pts, base_w)
    pygame.draw.lines(panel, _mix(pal["bolt"], int(140 * strobe)), False,
                      branch, 2)
    # 落雷點上一團光暈＋整片白幕（SRCALPHA，會壓過已畫好的雨絲，這是要的效果）
    g = 120
    _blit(panel, _sprite("glow", pal["bolt"], (g, g)),
          (pts[0][0] - g / 2, pts[0][1] - g / 2), int(120 * strobe))
    flash = pygame.Surface((w, h), pygame.SRCALPHA)
    flash.fill((255, 255, 255, int(46 * strobe)))
    panel.blit(flash, (0, 0))


def _draw_snow(panel, t: float, w: int, h: int, pal: dict) -> None:
    # 柔焦雪點（star 高斯點素材三種尺寸），速度/擺幅/大小全雜湊。
    for i in range(16):
        speed = 24 + _h(i, 61) * 34
        sway = 10 + _h(i, 62) * 14
        x = (_h(i, 63) * w) + math.sin(t * (0.7 + _h(i, 64) * 0.5) + i) * sway
        y = (t * speed + _h(i, 65) * (h + 8)) % (h + 8) - 4
        size = (5, 7, 9)[int(_h(i, 66) * 2.99)]
        spr = _sprite("star", pal["snow"], (size, size))
        _blit(panel, spr, (round(x) % w - size // 2, round(y) - size // 2),
              150 + int(_h(i, 67) * 100))


# ---------------------------------------------------------------- 玻璃前景：水滴/雨刷/黏雪

def _ease_io(p: float) -> float:
    """雨刷擺動的緩動（兩端慢、中段快）——機械臂的加減速。"""
    return 0.5 - math.cos(math.pi * max(0.0, min(1.0, p))) / 2


def _wiper_pivot(w: int, h: int) -> tuple:
    return (w + 26, h + 24)


def _wiper_angle_deg(tc: float) -> "float | None":
    """循環內時刻 tc 對應的雨刷角度（度，0=從支點垂直向上，逆時針為負）；
    不在掃動時段回 None（雨刷停放在面板底緣之下）。去程 -100→-2、回程原路
    返回。面板內容從右下角支點看出去落在 φ∈[-85°, -4°]，去程掃到 -2° 時
    必定蓋過全部水滴。"""
    if not (_WIPE_START <= tc < _WIPE_START + 2 * _WIPE_SWEEP_S):
        return None
    p = (tc - _WIPE_START) / _WIPE_SWEEP_S
    span = _WIPE_TO_DEG - _WIPE_FROM_DEG
    if p <= 1.0:
        return _WIPE_FROM_DEG + span * _ease_io(p)
    return _WIPE_TO_DEG - span * _ease_io(p - 1.0)


# 水滴尺寸表：r(3..8) → 烘焙母版 44×56 的縮放尺寸，固定 6 組。
_DROP_SIZES = {r: (r * 3, round(r * 3 * 56 / 44)) for r in range(3, 9)}


def _draw_glass_rain(panel, t: float, w: int, h: int, pal: dict) -> None:
    tc = t % WIPE_PERIOD_S
    # 去程雨刷「已經掃過」的最大角度：掃過的水滴永久消失（直到下一輪積聚）。
    wiped_to = -1e9
    if tc >= _WIPE_START:
        wiped_to = _WIPE_FROM_DEG + (_WIPE_TO_DEG - _WIPE_FROM_DEG) \
            * _ease_io((tc - _WIPE_START) / _WIPE_SWEEP_S)
    cx, py = _wiper_pivot(w, h)
    for i in range(_DROP_N):
        born = _h(i, 71) * (_WIPE_START - 0.8)
        if tc < born:
            continue
        x = _h(i, 72) * (w - 16) + 8
        y = _h(i, 73) * (h - 70) + 24
        phi = math.degrees(math.atan2(x - cx, py - y))
        if phi <= wiped_to:
            continue
        # 尺寸取偏斜分佈：小滴多、大滴少；只有大滴（r>=6）重到會下滑，
        # 滑動略帶加速並拖出細水痕。
        r = 3 + int(_h(i, 74) ** 2 * 6)
        age = tc - born
        slide = min(16.0, age ** 1.25 * 1.1) if r >= 6 else min(5.0, age * 0.5)
        if r >= 6 and slide > 3:
            pygame.draw.line(panel, _mix(pal["drop"], 46),
                             (round(x), round(y - 2)),
                             (round(x), round(y + slide - 2)), 1)
        spr = _sprite("drop", pal["drop"], _DROP_SIZES[r])
        _blit(panel, spr, (round(x - spr.get_width() / 2),
                           round(y + slide - spr.get_height() / 2)),
              int(255 * min(1.0, age / 0.25)))
    ang = _wiper_angle_deg(tc)
    if ang is not None:
        _draw_wiper_arm(panel, ang, w, h, pal, tc)


def _draw_wiper_arm(panel, ang_deg: float, w: int, h: int, pal: dict,
                    tc: float) -> None:
    """真車構型：臂根細、膠條粗、亮邊一條，全部沿臂徑向從右下角支點伸出。
    臂照樣掃過時鐘——水滴就積在時鐘玻璃上，不掃過去擦不掉，這正是 HTC 玻璃
    比喻的因果；角落支點保證任何掃角都是斜線構圖，不會出現貫穿全高的垂直
    直桿（見 _WIPE_FROM_DEG 註解的兩版失敗史）。膠條後緣帶一條淡濕痕，
    「正在把水推走」的因果才讀得出來。"""
    cx, py = _wiper_pivot(w, h)

    def pt(ang: float, r: float) -> tuple:
        a = math.radians(ang)
        return (cx + math.sin(a) * r, py - math.cos(a) * r)

    # 濕痕畫在膠條「來的方向」後面 2.5 度：去程在膠條下方、回程在上方。
    p = (tc - _WIPE_START) / _WIPE_SWEEP_S
    trail_side = -1.0 if p <= 1.0 else 1.0
    trail_ang = ang_deg + trail_side * 2.5
    pygame.draw.line(panel, _mix(pal["drop"], 30),
                     pt(trail_ang, 150), pt(trail_ang, 690), 12)
    pygame.draw.line(panel, pal["wiper"], pt(ang_deg, 0), pt(ang_deg, 150), 6)
    pygame.draw.line(panel, pal["wiper"], pt(ang_deg, 140), pt(ang_deg, 690), 10)
    pygame.draw.line(panel, pal["wiper_edge"], pt(ang_deg, 160), pt(ang_deg, 680), 2)
    end = pt(ang_deg, 690)
    pygame.draw.circle(panel, pal["wiper"], (round(end[0]), round(end[1])), 5)


def _draw_glass_snow(panel, t: float, w: int, h: int, pal: dict) -> None:
    """雪花黏附玻璃：各自淡入→停留→漸融，位置固定（黏住就不動了）。"""
    period, life = 9.0, 5.0
    flake = _sprite("flake", pal["snow"])
    for i in range(10):
        born = _h(i, 81) * period
        age = (t % period - born) % period
        if age > life:
            continue
        fade = min(age / 0.4, (life - age) / 1.2, 1.0)
        x = int(_h(i, 82) * (w - 20)) + 10
        y = int(_h(i, 83) * (h - 60)) + 20
        _blit(panel, flake, (x - flake.get_width() // 2,
                             y - flake.get_height() // 2), int(225 * fade))
