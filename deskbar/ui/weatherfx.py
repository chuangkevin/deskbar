"""左面板天氣場景層——HTC Sense 風格的動態天氣（2026-07-27 全面重寫，
同日寫實化二版：見「寫實化鐵則」）。

兩層結構，忠於 HTC Sense 的玻璃比喻（雨刷/雪花貼螢幕是它的招牌）：
- draw()：背景場景，畫在時鐘/文字「之前」——太陽光芒旋轉＋光暈呼吸、夜晚
  月亮星星、多雲視差、分景深雨絲＋濺落、雷雨閃電、雪花飄落、霧帶。
- draw_glass()：玻璃前景，畫在整個左欄內容「之後」（蓋在時鐘上）——雨天
  水滴積聚在玻璃上、每 WIPE_PERIOD_S 秒雨刷整片去回掃一趟抹掉水滴；雪天
  雪花黏附玻璃、漸融消失。只有雨/雷/雪族群有玻璃層，其餘 code 不畫。

座標一律透過 surface.subsurface() 裁切在 (x0, 0)-(x0+w, h) 內，任何座標
算錯也畫不出這個矩形。

節奏鐵則：t 是「浮點秒數」，由呼叫端用單調時鐘算好傳入（app._weather_t()）；
本模組是 (code, t, night) 的純函式，不得讀 pygame.time / time.time() 自行
計時——同一組參數永遠畫出同一張圖，測試與 filmstrip 工具都靠這個性質。
速度單位全部是「px/秒」，呼叫端跑 15fps 或 8fps 只影響流暢度、不影響速率。

寫實化鐵則（一版「有點假」的檢討，逐條對應）：
- 位置/大小/相位一律走 _h() 黃金比例雜湊，不用 (i*質數)%w——線性同餘會排出
  肉眼可辨的等距斜格，是「電子花車感」的最大來源。
- 雨絲每落完一輪重抽 x（雜湊 (i, layer, cycle)），不能永遠落在同幾條直線上。
- 雲 puff 用三層同心圓做軟邊＋底部壓暗一條，剪影式均勻 alpha 看起來像貼紙。
- 玻璃水滴橢圓化（高>寬）、尺寸取偏斜分佈（小滴多大滴少）、大滴會下滑並拖
  出細水痕；雨刷膠條後緣帶一條淡濕痕。
- 閃電每輪雜湊出 6 段鋸齒主幹＋一條分枝，畫三層寬度做輝光。
- 太陽光芒「寬淡線＋窄亮線」疊出錐形，長度逐道微變；光暈三圈漸層。

透明度手法：雨絲/星星/雪花/光芒這類「畫在純色背景上」的元素，不開 SRCALPHA
逐幀合成（400×480 的 RGBA 清空在 Pi Zero 2W 上燒不起），改用 _mix() 把顏色
預先朝背景色 lerp——在平坦背景上數學結果跟 alpha 合成完全一致，成本只剩一次
tuple 運算。真正會互相疊加的（雲朵、光暈、月亮、閃電白幕）才用 SRCALPHA。

快取鐵則：預繪 sprite 存在 _sprites dict——key 全部來自固定組合（雲 2 尺寸
×2 alpha、水滴 6 個量化尺寸、雪花 1 種，各 × 主題），物理上封頂，不是會
無限長大的容器；主題切換時透過 theme.register_cache_clear 整組清掉。
"""

from __future__ import annotations

import math

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
# 省電槓桿是 ambient_fps() 的分級幀率——雨/雷才值得 15fps，晴/雲/霧的最快可見
# 位移是雲 25px/s，8fps 下每幀 3px、肉眼無感，幀率砍半就是 Pi 的燒耗砍半。
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

# sprite 快取：key 全部來自固定組合（見模組 docstring 的快取鐵則）。
_sprites: dict = {}
build_count = 0


def _clear_cache() -> None:
    _sprites.clear()


theme.register_cache_clear(_clear_cache)


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
            "rain": theme.col((96, 122, 168)), "cloud": theme.col((151, 156, 168)),
            "cloud_hi": theme.col((186, 190, 200)),
            "sun": theme.col((238, 152, 42)), "ray": theme.col((240, 168, 66)),
            "glow": theme.col((242, 186, 96)), "star": theme.col((112, 116, 142)),
            "moon": theme.col((146, 150, 170)), "snow": theme.col((132, 142, 164)),
            "mist": theme.col((168, 172, 182)), "bolt": theme.col((222, 158, 30)),
            "splash": theme.col((120, 144, 184)),
            "drop": theme.col((96, 122, 168)), "drop_rim": theme.col((72, 96, 142)),
            "wiper": theme.col((88, 90, 96)), "wiper_edge": theme.col((140, 142, 148)),
        }
    return {
        "rain": theme.col((120, 150, 190)), "cloud": theme.col((214, 219, 229)),
        "cloud_hi": theme.col((246, 249, 255)),
        "sun": theme.col((255, 191, 82)), "ray": theme.col((255, 172, 64)),
        "glow": theme.col((255, 208, 126)), "star": theme.col((235, 238, 248)),
        "moon": theme.col((226, 228, 216)), "snow": theme.col((234, 240, 250)),
        "mist": theme.col((198, 204, 214)), "bolt": theme.col((255, 238, 176)),
        "splash": theme.col((150, 180, 216)),
        "drop": theme.col((150, 190, 235)), "drop_rim": theme.col((196, 220, 248)),
        "wiper": theme.col((105, 110, 118)), "wiper_edge": theme.col((182, 187, 194)),
    }


def _mix(color, alpha: int):
    """把 color 以 alpha/255 的比例朝主題背景色 lerp——在平坦背景上等價於
    alpha 合成，但可以直接用 pygame.draw.line/circle 畫實色（見模組 docstring）。"""
    a = max(0, min(255, alpha)) / 255.0
    bg = theme.C["bg"]
    return tuple(round(bg[i] + (color[i] - bg[i]) * a) for i in range(3))


def draw(surface, code: int, t: float, x0: int = 0, w: int = 400, h: int = 480,
         night: bool = False) -> None:
    """在 surface 的 (x0, 0)-(x0+w, h) 矩形內畫出 code 對應的天氣場景。

    t＝浮點秒數（見模組 docstring 的節奏鐵則）；night 由呼叫端依當下時刻判定，
    影響晴/多雲場景（太陽↔月亮星空）。code 對不到任何場景就完全不畫。
    """
    if w <= 0 or h <= 0:
        return
    rect = pygame.Rect(x0, 0, w, h).clip(surface.get_rect())
    if rect.width <= 0 or rect.height <= 0:
        return
    panel = surface.subsurface(rect)
    pal = _pal()
    if code in THUNDER_CODES:
        _draw_rain(panel, t, w, h, pal, code)
        _draw_lightning(panel, t, w, h, pal)
    elif code in RAIN_CODES:
        _draw_rain(panel, t, w, h, pal, code)
    elif code in SNOW_CODES:
        _draw_snow(panel, t, w, h, pal)
    elif code in FOG_CODES:
        _draw_fog(panel, t, w, h, pal)
    elif code in CLOUD_CODES:
        if night:
            if code == 1:
                _draw_stars(panel, t, w, h, pal, n=8)
                _draw_moon(panel, w, pal)
        elif code in (1, 2):
            _draw_sun(panel, t, w, pal, minor=(code == 2))
        _draw_clouds(panel, code, t, w, h, pal)
    elif code in CLEAR_CODES:
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
    # 光芒（12 道，慢速旋轉）：畫在光暈之前，讓光暈的 SRCALPHA 疊上來柔化根部。
    # 光芒要「長」——時鐘卡會蓋掉太陽本體的下半，靠伸出卡片邊緣的長光芒才看得出
    # 後面有顆太陽在轉（首版光芒只到 52px，整顆太陽幾乎被時鐘吃掉）。
    # 寬淡線＋窄亮線疊出錐形；長度逐道 ±12% 微變，去掉「機械齒輪」感。
    base = 150 if not minor else 105
    r1 = 30 * scale
    for k in range(12):
        a = math.radians(t * _SUN_RAY_DEG_PER_S + k * 30)
        ca, sa = math.cos(a), math.sin(a)
        r2 = (88 + math.sin(t * 1.1) * 4) * scale * (0.88 + 0.24 * _h(k, 5))
        p1 = (cx + ca * r1, cy + sa * r1)
        p2 = (cx + ca * r2, cy + sa * r2)
        pygame.draw.line(panel, _mix(pal["ray"], int(base * 0.45)), p1, p2, 5)
        pygame.draw.line(panel, _mix(pal["ray"], base), p1, p2, 2)
    # 呼吸光暈（三圈 SRCALPHA 漸層，半徑 ±5px 慢速呼吸）
    breathe = math.sin(t * 0.55) * 5
    for base_r, alpha in ((92, 14), (64, 30), (42, 52)):
        r = max(1, int(round(base_r * scale + breathe)))
        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*pal["glow"], alpha), (r, r), r)
        panel.blit(glow, (cx - r, cy - r))
    pygame.draw.circle(panel, _mix(pal["sun"], 235 if not minor else 170),
                       (cx, cy), int(20 * scale))


def _draw_moon(panel, w: int, pal: dict) -> None:
    # 月亮不能沿用太陽的位置：太陽被時鐘卡蓋住還有 88px 長光芒撐場面，月亮
    # 沒有光芒，放 (w-52,38) 會整顆縮在末張牌卡後面、只剩一小角灰鰭（審查
    # 實測遮蔽約九成）。改放右上角的無牌區（牌卡右緣 x=366 之外），整顆可見，
    # 再補一圈冷色月暈讓它跟太陽一樣有「探出來」的存在感。
    cx, cy = w - 18, 30
    for r, alpha in ((30, 22), (20, 36)):
        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*pal["moon"], alpha), (r, r), r)
        panel.blit(glow, (cx - r, cy - r))
    pygame.draw.circle(panel, _mix(pal["moon"], 215), (cx, cy), 14)
    # 亮面上撒兩三個隕石坑（比月面暗一階的小圓），不然是張平光圓片。
    for k, (dx, dy, r) in enumerate(((3, 4, 3), (7, -1, 2), (1, 9, 2))):
        pygame.draw.circle(panel, _mix(pal["moon"], 150), (cx + dx, cy + dy), r)
    # 用背景色圓偏移蓋出弦月缺口——這層畫在場景最底、下面必定是純背景色，
    # 拿 bg 實色「挖洞」不會蓋掉任何東西（會蓋掉一點月暈，正好是弦月的暗面）。
    pygame.draw.circle(panel, theme.C["bg"], (cx - 6, cy - 4), 12)


def _draw_stars(panel, t: float, w: int, h: int, pal: dict, n: int) -> None:
    for i in range(n):
        x = int(_h(i, 11) * (w - 8)) + 4
        y = int(_h(i, 12) * h * 0.52)
        speed = 0.8 + _h(i, 13) * 1.6          # 每顆星自己的閃爍節奏
        tw = math.sin(t * speed + _h(i, 14) * 6.28)
        alpha = int((70 + 110 * _h(i, 15)) + 90 * tw)
        if alpha <= 12:
            continue                           # 閃到最暗的那幾顆這一幀乾脆熄滅
        r = 2 if _h(i, 16) > 0.72 else 1
        pygame.draw.circle(panel, _mix(pal["star"], alpha), (x, y), r)
        if r == 2 and tw > 0.6:                # 亮星在最亮時刻加十字光芒
            c = _mix(pal["star"], alpha // 2)
            pygame.draw.line(panel, c, (x - 5, y), (x + 5, y))
            pygame.draw.line(panel, c, (x, y - 5), (x, y + 5))


# ---------------------------------------------------------------- 雲/霧

def _puff(name: str, pw: int, ph: int, pal: dict, alpha: int) -> "pygame.Surface":
    global build_count
    # alpha 一定要進 key：陰天(84)與多雲(66)共用同兩種 puff 尺寸，key 少了 alpha
    # 會讓「開機後誰先畫」決定所有雲的厚度、破壞純函式契約（審查實測：code 2
    # 先畫過之後，code 3 的幀會逐位元等於 code 2 的透明度）。key 組合仍是固定
    # 集合（2 尺寸 × 2 alpha × 主題），不會無界成長。
    key = (name, alpha, theme.current_theme())
    s = _sprites.get(key)
    if s is None:
        build_count += 1
        s = _build_puff(pw, ph, pal, alpha)
        _sprites[key] = s
    return s


def _build_puff(pw: int, ph: int, pal: dict, alpha: int) -> "pygame.Surface":
    """軟邊雲朵。剪影規則（飛碟事故的教訓）：底座必須「內縮」、bump 必須撐滿
    寬度——底座比 bump 群寬會伸出兩側屋簷，整朵直接變飛碟。四顆圓取
    小-大-大-小的經典雲形，底座是圓角矩形（平底、圓端）。

    軟邊：三層同心 pass（大而淡→小而實）；SRCALPHA 上 draw 是「覆寫」不是
    疊加，所以每層要把全部形狀畫完再進下一層，且陰影/受光只能動色調、不能動
    alpha（動 alpha 會在雲身上開出透明度斷層——首版的飛碟黑洞就是這樣來的）。"""
    s = pygame.Surface((pw, ph), pygame.SRCALPHA)
    bumps = [(0.18, 0.60, 0.19), (0.41, 0.44, 0.27),
             (0.61, 0.42, 0.25), (0.82, 0.58, 0.17)]
    base = pygame.Rect(int(pw * 0.06), int(ph * 0.52),
                       int(pw * 0.88), int(ph * 0.40))
    for ring_scale, ring_alpha in ((1.14, 0.28), (1.06, 0.60), (1.0, 1.0)):
        a = int(alpha * ring_alpha)
        for fx, fy, fr in bumps:
            pygame.draw.circle(s, (*pal["cloud"], a),
                               (int(pw * fx), int(ph * fy)),
                               int(ph * fr * ring_scale))
        grow = int(ph * (ring_scale - 1) * 1.5)
        rect = base.inflate(grow, grow)
        pygame.draw.rect(s, (*pal["cloud"], a), rect,
                         border_radius=max(1, rect.height // 2))
    # 頂部受光：兩顆大 bump 的上緣畫亮一階色調的弧（同 alpha，安全）。
    for fx, fy, fr in bumps[1:3]:
        r = int(ph * fr)
        rect = pygame.Rect(int(pw * fx) - r, int(ph * fy) - r, r * 2, r * 2)
        pygame.draw.arc(s, (*pal["cloud_hi"], alpha), rect,
                        math.radians(35), math.radians(145), 3)
    return s


# (lane y 比例, 速度 px/s, 尺寸) ——三層視差：低的近、快、大。
_CLOUD_LANES = ((0.585, 10.0, "l"), (0.695, 17.0, "s"), (0.80, 25.0, "l"),
                (0.50, 6.0, "s"))


def _draw_clouds(panel, code: int, t: float, w: int, h: int, pal: dict) -> None:
    n = {1: 2, 2: 3, 3: 4}.get(code, 3)
    alpha = 66 if code < 3 else 84         # 陰天雲更厚重
    for i in range(n):
        frac, speed, size = _CLOUD_LANES[i]
        pw, ph = (190, 76) if size == "l" else (140, 58)
        blob = _puff(f"puff_{size}", pw, ph, pal, alpha)
        span = w + pw + 60                 # 進出場都要完整走完整個 puff 寬
        cx = (t * speed + _h(i, 21) * span) % span - pw
        cy = h * frac + math.sin(t * 0.1 + i * 2.2) * 3   # 極慢的上下漂
        panel.blit(blob, (round(cx), round(cy - ph / 2)))


def _draw_fog(panel, t: float, w: int, h: int, pal: dict) -> None:
    # 霧帶必須窄於面板寬，圓頭端點才會進畫面——等寬霧帶橫移時可視區全是均勻
    # 中段，數學上有動、視覺上完全靜止（首版實際踩過）。窄帶＋端點可見＋濃度
    # 呼吸三者一起才有霧的流動感。
    band_h = 26
    for i in range(3):
        bw = int(w * (0.70 + 0.16 * _h(i, 31))) - i * 24
        y = int(h * 0.58) + i * 46
        x = (w - bw) / 2 + math.sin(t * 0.22 + _h(i, 32) * 6.28) * 52
        alpha = int(34 + 8 * math.sin(t * 0.5 + i * 2.3))
        band = pygame.Surface((bw, band_h), pygame.SRCALPHA)
        pygame.draw.rect(band, (*pal["mist"], alpha), band.get_rect(),
                         border_radius=band_h // 2)
        panel.blit(band, (round(x), y))


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
    for pts_, base_w in ((pts, 7), (pts, 4), (pts, 2)):
        a = {7: 60, 4: 120, 2: 235}[base_w]
        pygame.draw.lines(panel, _mix(pal["bolt"], int(a * strobe)), False,
                          pts_, base_w)
    pygame.draw.lines(panel, _mix(pal["bolt"], int(140 * strobe)), False,
                      branch, 2)
    # 整片白幕（SRCALPHA，會壓過已畫好的雨絲，這是要的效果）
    flash = pygame.Surface((w, h), pygame.SRCALPHA)
    flash.fill((255, 255, 255, int(46 * strobe)))
    panel.blit(flash, (0, 0))


def _draw_snow(panel, t: float, w: int, h: int, pal: dict) -> None:
    for i in range(16):
        speed = 24 + _h(i, 61) * 34
        sway = 10 + _h(i, 62) * 14
        x = (_h(i, 63) * w) + math.sin(t * (0.7 + _h(i, 64) * 0.5) + i) * sway
        y = (t * speed + _h(i, 65) * (h + 8)) % (h + 8) - 4
        r = 1 + int(_h(i, 66) * 2.6)
        alpha = 120 + int(_h(i, 67) * 110)
        pygame.draw.circle(panel, _mix(pal["snow"], alpha),
                           (round(x) % w, round(y)), r)


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


def _drop_sprite(r: int, pal: dict) -> "pygame.Surface":
    """玻璃水滴：橢圓（高>寬，貼在玻璃上被重力拉長）＋暗滴緣＋偏心高光。
    r 由呼叫端量化到 3..8 的整數，key 組合封頂 6 個 × 主題。"""
    global build_count
    key = (f"drop_{r}", theme.current_theme())
    s = _sprites.get(key)
    if s is None:
        build_count += 1
        rw, rh = r, int(r * 1.3)
        s = pygame.Surface((rw * 2 + 4, rh * 2 + 4), pygame.SRCALPHA)
        c = (rw + 2, rh + 2)
        body = pygame.Rect(c[0] - rw, c[1] - rh, rw * 2, rh * 2)
        pygame.draw.ellipse(s, (*pal["drop"], 88), body)
        pygame.draw.ellipse(s, (*pal["drop_rim"], 150), body, 1)
        # 底緣加深一彎（透鏡聚光的暗邊），高光偏左上。
        pygame.draw.arc(s, (*pal["drop_rim"], 190), body,
                        math.radians(215), math.radians(325), 2)
        pygame.draw.circle(s, (255, 255, 255, 150),
                           (c[0] - max(1, rw // 2), c[1] - max(1, rh // 2)),
                           max(1, rw // 3))
        _sprites[key] = s
    return s


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
        spr = _drop_sprite(r, pal)
        spr.set_alpha(int(255 * min(1.0, age / 0.25)))
        if r >= 6 and slide > 3:
            pygame.draw.line(panel, _mix(pal["drop"], 46),
                             (round(x), round(y - 2)),
                             (round(x), round(y + slide - 2)), 1)
        panel.blit(spr, (round(x - spr.get_width() / 2),
                         round(y + slide - spr.get_height() / 2)))
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
    for i in range(10):
        born = _h(i, 81) * period
        age = (t % period - born) % period
        if age > life:
            continue
        fade = min(age / 0.4, (life - age) / 1.2, 1.0)
        x = int(_h(i, 82) * (w - 20)) + 10
        y = int(_h(i, 83) * (h - 60)) + 20
        spr = _flake_sprite(pal)
        spr.set_alpha(int(210 * fade))
        panel.blit(spr, (x - spr.get_width() // 2, y - spr.get_height() // 2))


def _flake_sprite(pal: dict) -> "pygame.Surface":
    global build_count
    key = ("flake", theme.current_theme())
    s = _sprites.get(key)
    if s is None:
        build_count += 1
        s = pygame.Surface((11, 11), pygame.SRCALPHA)
        c = (*pal["snow"], 235)
        pygame.draw.line(s, c, (5, 0), (5, 10))
        pygame.draw.line(s, c, (0, 5), (10, 5))
        pygame.draw.line(s, c, (1, 1), (9, 9))
        pygame.draw.line(s, c, (9, 1), (1, 9))
        pygame.draw.circle(s, c, (5, 5), 2)
        _sprites[key] = s
    return s
