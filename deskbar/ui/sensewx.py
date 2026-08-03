"""左欄 Sense 天氣層：天氣是「有實體的前景角色」——蓬鬆積雲飄在翻牌時鐘
前面、晴天亮面太陽球從時鐘角落探出，加上 Sense 式排版（城市/天況靠左、
大字溫度靠右）。致敬 HTC Sense 的三個招牌：白卡時鐘、天氣主角疊卡、大溫度。

素材：tools/gen_scene_assets.py 烘焙的 cumulus_0/1（fBm 體積雲）與
sun_ball（亮面太陽球），中性白執行期染色。t 是單調浮點秒（氛圍幀驅動
雲的極慢漂移）；draw_char 在 flipclock 之後呼叫（前景），draw_info 畫
文字區塊。
"""

from __future__ import annotations

import math

from deskbar.ui import theme
from deskbar.ui.scenes import _scene_sprite
from deskbar.weather import code_text
from deskbar.ui.weatherfx import (CLEAR_CODES, CLOUD_CODES, FOG_CODES,
                                  RAIN_CODES, SNOW_CODES, THUNDER_CODES)

import pygame

CLOCK = pygame.Rect(24, 34, 316, 96)     # 與 _render_panel 的 flipclock 參數一致
                                         # （無冒號卡：4 卡＋中央空隙 ≈ 316px）


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.text_surface(s, size, color, bold=bold)
    surface.blit(img, img.get_rect(**{anchor: (x, y)}))


def draw_char(surface, code: int, t: float, night: bool) -> None:
    """天氣主角，疊在時鐘「前面」（呼叫端在 flipclock 之後呼叫）。
    晴天白晝＝太陽球探出時鐘右上；有雲族群＝積雲壓在時鐘下緣；
    雨雪雷＝暗色積雲（雨絲/玻璃層仍由 weatherfx 負責）。"""
    drift = math.sin(t * 0.05) * 10
    bob = math.sin(t * 0.11) * 3
    if code in CLEAR_CODES:
        if night:
            return                        # 夜晴：背景月亮星空即主角，不搶戲
        sun = _scene_sprite("sun_ball", (255, 186, 66))
        surface.blit(sun, (CLOCK.right - 84 + drift * 0.4,
                           CLOCK.top - 42 + bob))
        return
    if code in CLOUD_CODES:
        tint = (250, 250, 252) if not night else (208, 214, 228)
        sizes = ((252, 138), (176, 96)) if code >= 2 else ((208, 114),)
    elif code in RAIN_CODES or code in THUNDER_CODES:
        tint = (152, 160, 176) if code in RAIN_CODES else (120, 126, 142)
        sizes = ((252, 138), (176, 96))
    elif code in SNOW_CODES:
        tint = (232, 238, 248)
        sizes = ((252, 138), (176, 96))
    elif code in FOG_CODES:
        return                            # 霧：weatherfx 的霧帶已是主角
    else:
        return
    anchors = ((CLOCK.left + 96, CLOCK.bottom - 64), (CLOCK.right - 96, CLOCK.top - 26))
    for i, (cw, ch) in enumerate(sizes):
        spr = pygame.transform.smoothscale(
            _scene_sprite(f"cumulus_{i % 2}", tint), (cw, ch))
        ax, ay = anchors[i % 2]
        surface.blit(spr, (ax - cw // 2 + drift * (1 if i == 0 else -0.6),
                           ay - ch // 2 + bob * (1 if i == 0 else -1)))


def draw_info(surface, w, now) -> None:
    """Sense 排版：城市（左、粗）＋天況（左下、灰），大字溫度靠右、
    高低溫小字在其下。取代一版的單行「陰 30° 南港」（驗收：排版不對）。"""
    age = (now - w.fetched_at).total_seconds()
    stale = "（舊）" if age > 7200 else ""
    _text(surface, w.label, 26, theme.C["text"], 24, 196, bold=True)
    _text(surface, f"{code_text(w.code)}{stale}", 20, theme.C["muted"], 24, 232)
    _text(surface, f"{round(w.temp)}°", 58, theme.C["text"], 376, 186,
          anchor="topright", bold=True)
    _text(surface, f"{round(w.tmin)}° / {round(w.tmax)}°", 18, theme.C["muted"],
          376, 254, anchor="topright")
