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


def _pose(t: float) -> tuple[float, float, float, float]:
    """Return the fixed celestial anchor plus shared atmospheric motion."""
    return CLOCK.centerx, CLOCK.bottom - 4, math.sin(t * 0.11) * 3, \
        math.sin(t * 0.07) * 7


def draw_celestial(surface, code: int, t: float, night: bool) -> None:
    """Draw physically distant sun/moon at the authored fixed position."""
    from deskbar.ui import weatherfx
    if code not in CLEAR_CODES and code not in (1, 2):
        return
    cx, cy, bob, _sway = _pose(t)
    if night:
        moon = weatherfx._sprite("moon", (232, 232, 222), (62, 62))
        moon.set_alpha(255)
        surface.blit(moon, (cx - 31, cy - 42 + bob))
    else:
        breathe = int(96 + 44 * math.sin(t * 0.5))
        glow = weatherfx._sprite("glow", (255, 200, 110), (190, 190))
        glow.set_alpha(breathe)
        surface.blit(glow, (cx - 95, cy - 90 + bob))
        surface.blit(_scene_sprite("sun_ball", (255, 186, 66)),
                     (cx - 80, cy - 78 + bob))


def draw_foreground(surface, code: int, t: float, night: bool) -> None:
    """Draw local cloud, fog, and storm matter in front of the clock plane."""
    from deskbar.ui import weatherfx
    if code in CLEAR_CODES:
        return
    cx, cy, bob, sway = _pose(t)
    heavy = code in (63, 65, 66, 67, 81, 82)
    if code in FOG_CODES:
        mist = weatherfx._sprite("fog", (216, 220, 228) if not night
                                 else (176, 182, 198), (170, 48))
        mist.set_alpha(170)
        surface.blit(mist, (cx - 85 + sway, cy - 12 + bob))
        return
    if code in (1, 2):
        tint = (250, 250, 252) if not night else (200, 208, 226)
        spec = [((116, 64), -30, 8)] if code == 1 else                [((132, 72), -36, 6), ((104, 58), 34, 14)]
    elif code == 3:
        tint = (236, 238, 244) if not night else (188, 196, 216)
        spec = [((136, 74), -36, 4), ((112, 62), 36, 12)]
    elif code in THUNDER_CODES:
        tint = (104, 110, 128) if not night else (84, 90, 108)
        spec = [((150, 82), -38, 4), ((118, 66), 38, 14)]
        tc = t % weatherfx.FLASH_PERIOD_S
        if tc < 0.12 or 0.20 <= tc < 0.32:
            tint = (234, 238, 250)
    elif code in RAIN_CODES:
        if heavy:
            tint = (122, 130, 148) if not night else (96, 104, 122)
            spec = [((150, 82), -38, 4), ((118, 66), 38, 14)]
        else:
            tint = (160, 168, 184) if not night else (128, 136, 154)
            spec = [((136, 74), -36, 4), ((112, 62), 36, 12)]
    elif code in SNOW_CODES:
        tint = (240, 244, 252) if not night else (206, 214, 232)
        spec = [((136, 74), -36, 4), ((112, 62), 36, 12)]
    else:
        return
    sway *= 1.6 if (heavy or code in THUNDER_CODES) else 1.0
    for i, ((cw, ch), dx, dy) in enumerate(spec):
        spr = _scene_sprite(f"cumulus_{i % 2}", tint, (cw, ch))
        sx = sway if i % 2 == 0 else -sway * 0.7
        surface.blit(spr, (round(cx + dx - cw // 2 + sx),
                           round(cy + dy - ch // 2 + bob * (0.6 if i else 1.0))))


def draw_char(surface, code: int, t: float, night: bool) -> None:
    """Compatibility compositor for callers that do not own explicit depth planes.

    天氣主角＝中央徽章：常駐在 HH 與 MM 之間、跨在時鐘下緣（Sense 經典
    構圖，參考圖定案）——日/月在後、積雲在前、垂進下方資訊區。

    天氣 × 早晚矩陣：
      晴        白晝＝太陽球＋光暈呼吸；夜＝隕坑月面
      晴時多雲  日/月＋一朵雲前遮
      多雲      日/月＋雙雲（參考圖的招牌 pose）
      陰        雙灰雲、無日月
      毛毛雨/雨 暗雲（雨絲/玻璃滴由 weatherfx 背景與玻璃層負責）
      暴雨      更暗更大的雙雲＋搖曳加快
      雷雨      墨雲；閃電 strobe 時整組被照亮（與 weatherfx 同一時間軸）
      雪        霜白雲（雪花由背景層落）
      霧        一縷薄霧橫過（背景霧帶仍是主角）
    動態：日暈呼吸（~12s）、雲對向搖曳（~90s 往返）、整組輕微浮沉。"""
    draw_celestial(surface, code, t, night)
    draw_foreground(surface, code, t, night)


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
