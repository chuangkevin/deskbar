import os

import pygame

# 雙主題色板（2026-07-27 重調）：實機是低色域低對比 TN 類面板，舊版多層深灰
# （0f0f0f/1a1a1a/262626 那個量級）在面板上會塌陷成一坨、次要文字掉進黑階看不見。
# 深色改走「純黑底＋高對比字/線」；新增淺色（暖紙感）供設定頁切換。
# 兩套 key 完全一致，缺一個 set_theme() 組字典時就會直接 KeyError，不會悄悄退化。
_PALETTES_RAW = {
    "dark": {
        "usage_bar": (217, 119, 87),
        "bg": (0, 0, 0), "card": (30, 30, 30), "panel_line": (70, 70, 70),
        "grid": (55, 55, 55), "text": (255, 255, 255), "text2": (212, 212, 212),
        "muted": (186, 186, 186), "now": (255, 138, 101), "now_text": (60, 20, 8),
        "warn": (255, 105, 105), "ok": (60, 220, 170),
        # flipclock 數字卡底色／分隔線（原 flipclock.py 模組級 CARD/SPLIT 常量）。
        "clock_card": (34, 34, 34), "clock_split": (12, 12, 12),
        # monthgrid 窗口外日期數字（原 OUT_OF_WINDOW_DATE_COLOR 常量）。
        "date_dim": (150, 150, 150),
        # settings_view 移除帳號二次確認底條（原 theme.col((40, 20, 20)) 字面值）。
        "danger_bg": (40, 20, 20),
        # dashboard「未同步範圍」暗帶：純黑底下 (20,20,20) 幾乎會被吃掉，
        # 改用能跟 bg 拉出可辨識差距的中灰，兩色帶著 alpha=170 疊上去才看得見。
        "dim_band": (60, 60, 60),
    },
    "light": {
        "usage_bar": (184, 86, 54),
        "bg": (242, 240, 235), "card": (255, 255, 255), "panel_line": (198, 194, 186),
        "grid": (216, 212, 204), "text": (26, 26, 26), "text2": (70, 70, 70),
        "muted": (122, 120, 114), "now": (200, 88, 56), "now_text": (255, 255, 255),
        "warn": (178, 44, 44), "ok": (20, 140, 110),
        "clock_card": (255, 255, 255), "clock_split": (214, 210, 202),
        "date_dim": (168, 164, 156),
        "danger_bg": (250, 218, 210),
        "dim_band": (206, 202, 194),
    },
}

# 帳號色（4 組 [(main, fill), ...]）：main＝標題字／泳道字，fill＝件數膠囊、事件
# 色塊底。深色版 main 用高亮飽和色、fill 用能從純黑底分離出來的深色；淺色版
# main 用深濃色（在白底上仍清楚）、fill 用淡色底——呼叫端「標題字=main、
# 色塊底=fill」的慣例兩套下都不用改。
_ACCOUNTS_RAW = {
    "dark": [
        ((0, 228, 180), (0, 88, 66)),      # teal
        ((108, 180, 255), (16, 84, 150)),  # blue
        ((186, 166, 255), (74, 60, 160)),  # purple
        ((255, 150, 110), (120, 52, 28)),  # clay
    ],
    "light": [
        ((0, 112, 88), (198, 236, 224)),     # teal
        ((22, 92, 168), (206, 226, 250)),    # blue
        ((88, 62, 170), (226, 216, 248)),    # purple
        ((176, 84, 48), (248, 220, 204)),    # clay
    ],
}

PALETTES = _PALETTES_RAW   # 對外別名：供測試/工具檢查兩套 key 是否一致

# BGR 色板開關：某些面板排線只吃 BGR 順序，接反了全螢幕顏色就會錯置。
# DESKBAR_BGR=1 時，set_theme() 套用當下主題時就把 C／ACCOUNT_COLORS 所有顏色
# (r,g,b)→(b,g,r)；沒設就完全不碰，dev 模式零行為差異。只在模組載入當下讀一次
# env，之後 col() 沿用同一個旗標，不必每次呼叫都重新查 os.environ。
_BGR = os.environ.get("DESKBAR_BGR") == "1"


def col(rgb):
    """給 repo 內其他模組寫死的彩色 RGB(A) 常量包一層：DESKBAR_BGR=1 時交換 R/B
    通道，否則原樣傳回。灰階對稱色（r==g==b）交換前後不變，這類常量可以不包，
    包了也無害——這支只負責「開關開著時才動手」，不負責判斷要不要包。"""
    if _BGR:
        r, g, b, *rest = rgb
        return (b, g, r, *rest)
    return tuple(rgb)


# C／ACCOUNT_COLORS 維持模組級容器物件（dict／list），set_theme() 一律
# in-place clear+update／clear+extend，不重新綁定名字——這樣任何拿到這兩個物件
# 參照的呼叫端（例如未來出現的 from-import）都會跟著切換，不會抱著切換前的舊物件。
C: dict = {}
ACCOUNT_COLORS: list = []

_current_theme = "dark"
# globals().get(...) 而非直接 `= []`：theme 模組在測試裡會被 importlib.reload()
# 用來驗證 DESKBAR_BGR 讀取行為（見 test_theme_bgr_headless.py），reload 會重跑
# 這段模組碼，但登記快取清除的 flipclock／qr／weatherfx 等模組並不會跟著重新
# import，只是單純 import theme 這支模組——若這裡無條件 `= []`，reload 一次就會
# 把它們先前登記的 callback 永久清空，之後任何 set_theme() 都清不到那些快取。
# 用 globals().get() 在同一個模組物件的既有命名空間裡找舊的 list 沿用，
# reload 前後容器身分不變，只有真的第一次 import 時才會是全新空 list。
_cache_clear_fns: list = globals().get("_cache_clear_fns", [])


def register_cache_clear(fn) -> None:
    """登記一個「主題切換時要清掉」的模組級快取回呼。凡是把顏色烤進快取
    Surface 的模組（flipclock 的數字卡、qr／weatherfx 的單槽底圖快取）都應該在
    自己模組載入時呼叫這支登記，set_theme() 會在套用新色板後逐一呼叫。
    fn 應冪等、不吃參數——呼叫端只負責清空自己的快取容器，不必知道新主題是誰。"""
    _cache_clear_fns.append(fn)


def current_theme() -> str:
    return _current_theme


def set_theme(name: str) -> None:
    """切換主題：套用 PALETTES[name]／對應帳號色到 C／ACCOUNT_COLORS（BGR 開關
    在這裡套用，palette 本身存的是原始未交換值），再呼叫所有已登記的快取清除
    回呼。name 不是 dark/light 就靜默退回 dark，不拋例外——設定檔可能被手動
    改壞，畫面渲染不該因此整個炸掉。"""
    global _current_theme
    _current_theme = name if name in _PALETTES_RAW else "dark"
    palette = _PALETTES_RAW[_current_theme]
    accounts = _ACCOUNTS_RAW[_current_theme]

    new_c = {k: col(v) for k, v in palette.items()}
    C.clear()
    C.update(new_c)

    new_accounts = [(col(main), col(fill)) for main, fill in accounts]
    ACCOUNT_COLORS.clear()
    ACCOUNT_COLORS.extend(new_accounts)

    for fn in _cache_clear_fns:
        fn()


set_theme("dark")   # 模組載入即套用預設深色，維持「import 完就能用」的既有行為


_FONT_PATHS = [
    os.environ.get("DESKBAR_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
]
_font_cache: dict = {}


def font(size: int) -> "pygame.font.Font":
    if not pygame.font.get_init():
        pygame.font.init()
        _font_cache.clear()
    if size not in _font_cache:
        f = None
        for p in _FONT_PATHS:
            if p and os.path.exists(p):
                f = pygame.font.Font(p, size)
                break
        if f is None:
            name = pygame.font.match_font("pingfangtc,pingfang,helvetica,arial") or None
            f = pygame.font.Font(name, size)
        _font_cache[size] = f
    return _font_cache[size]


def account_color(idx: int):
    return ACCOUNT_COLORS[idx % len(ACCOUNT_COLORS)]


def truncate_to_width(text: str, font: "pygame.font.Font", max_width: float) -> str:
    """單行量測式截斷：整段放得下就原樣傳回；放不下就逐字縮短、尾端補「…」，
    直到量出來的寬度 <= max_width 為止。連「一個字＋…」都放不下就回傳空字串
    （呼叫端應該乾脆不畫，而不是硬塞一個看不清楚的省略號）。"""
    if not text or max_width <= 0:
        return ""
    if font.size(text)[0] <= max_width:
        return text
    for i in range(len(text), 0, -1):
        candidate = text[:i] + "…"
        if font.size(candidate)[0] <= max_width:
            return candidate
    return ""


def wrap_lines(text: str, font: "pygame.font.Font", max_width: float,
              max_lines: int) -> list[str]:
    """把 text 依 max_width 逐字元量測分行，最多 max_lines 行。

    英文單字中間量測到超界時，會回退到該行最近的空白處斷行，避免把一個英文字
    從中間切開；中文字之間沒有空白可回退，量到超界就直接斷（逐字累積）。
    第 max_lines 行若還有放不下的內容，尾端縮到能放下再補「…」。
    """
    if not text or max_width <= 0 or max_lines <= 0:
        return []
    lines: list[str] = []
    remaining = text.strip()
    while remaining and len(lines) < max_lines:
        if font.size(remaining)[0] <= max_width:
            lines.append(remaining)
            remaining = ""
            break
        cut = len(remaining)
        for i in range(1, len(remaining) + 1):
            if font.size(remaining[:i])[0] > max_width:
                cut = max(1, i - 1)
                break
        line = remaining[:cut]
        # 還沒斷在空白上、且這一截裡有空白可回退——回退到該空白處，
        # 避免英文單字被硬生生切一半（CJK 逐字之間沒有空白，天然不受影響）。
        if cut < len(remaining) and remaining[cut] != " " and " " in line:
            back = line.rfind(" ")
            if back > 0:
                cut = back
                line = remaining[:cut]
        lines.append(line.rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        last = lines[-1] if lines else ""
        while last and font.size(last + "…")[0] > max_width:
            last = last[:-1]
        lines[-1] = (last + "…") if last else "…"
    return lines
