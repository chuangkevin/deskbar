"""日光儀：貼著螢幕頂緣的全寬 8px 日光帶——1920px 就是一天 24 小時。

左端 00:00、右端 24:00，底色是當日的光線劇本（夜→晨昏→白晝的漸層，
日出日落時刻由 NOAA 簡化算法從經緯度純數學算出，不打任何 API）；
「現在」是一顆會走的光點（白晝金色太陽、夜裡冷白月亮），日出日落位置
各有一道細刻痕。它是常駐 overlay，跟中欄任何內容共存，一眼掃過去就
知道「今天走到哪了、離天黑還多遠」。

快取：漸層帶每天只算一次（key=日期×主題×寬度），標記逐分鐘畫在 blit
之後——分鐘級全量重繪（app 既有節奏）就足以讓光點順順地走。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pygame

from deskbar.ui import theme

BAND_H = 8
_ZENITH = 90.833          # 官方日出日落定義：太陽中心天頂角（含大氣折射）

_cache: dict = {}         # (isodate, theme, w) -> band Surface；一天最多 2 筆/主題


def _clear_cache() -> None:
    _cache.clear()


theme.register_cache_clear(_clear_cache)


def sun_times(date, lat: float, lon: float, tz) -> tuple:
    """NOAA 簡化日出日落：回傳當地時區的 (sunrise, sunset) datetime。
    極晝/極夜（cos 超界）回 (None, None)——台北用不到，但數學要誠實。"""
    n = date.timetuple().tm_yday
    results = []
    for rising in (True, False):
        lng_hour = lon / 15.0
        t = n + ((6 if rising else 18) - lng_hour) / 24.0
        m = 0.9856 * t - 3.289
        l = (m + 1.916 * math.sin(math.radians(m))
             + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360.0
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360.0
        ra += (math.floor(l / 90) - math.floor(ra / 90)) * 90    # 對齊象限
        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(_ZENITH))
                 - sin_dec * math.sin(math.radians(lat))) \
            / (cos_dec * math.cos(math.radians(lat)))
        if not -1.0 <= cos_h <= 1.0:
            return (None, None)
        h = (360.0 - math.degrees(math.acos(cos_h))) if rising \
            else math.degrees(math.acos(cos_h))
        h /= 15.0
        t_local = h + ra / 15.0 - 0.06571 * t - 6.622
        ut = (t_local - lng_hour) % 24.0
        base = datetime(date.year, date.month, date.day, tzinfo=tz)
        offset = tz.utcoffset(base).total_seconds() / 3600.0
        results.append(base + timedelta(hours=(ut + offset) % 24.0))
    return tuple(results)


def _lerp(a, b, p: float) -> tuple:
    p = max(0.0, min(1.0, p))
    return tuple(round(a[i] + (b[i] - a[i]) * p) for i in range(3))


# 光線劇本的關鍵色（依主題微調亮度；晨昏 ±40 分鐘做平滑過渡）
def _phase_colors() -> dict:
    if theme.current_theme() == "light":
        return {"night": (168, 174, 196), "twilight": (232, 168, 96),
                "day": (240, 206, 120)}
    return {"night": (36, 44, 86), "twilight": (196, 116, 48),
            "day": (168, 136, 62)}


TWILIGHT_MIN = 40.0       # 晨昏過渡帶寬度（日出日落前後各 N 分鐘）


def _color_at(minute: float, rise_m: float, set_m: float, pal: dict) -> tuple:
    """一天中第 minute 分鐘的帶色：夜↔晨昏↔晝的平滑內插。"""
    for edge, day_side in ((rise_m, True), (set_m, False)):
        d = minute - edge
        if abs(d) <= TWILIGHT_MIN:
            p = (d / TWILIGHT_MIN + 1) / 2          # 0=夜側, 1=晝側
            if not day_side:
                p = 1 - p
            if p < 0.5:
                return _lerp(pal["night"], pal["twilight"], p * 2)
            return _lerp(pal["twilight"], pal["day"], (p - 0.5) * 2)
    return pal["day"] if rise_m < minute < set_m else pal["night"]


def _resolve(now, lat: float, lon: float, rise, sset) -> tuple:
    """日出日落來源決策：open-meteo 的當日真值優先（呼叫端從天氣快照傳入），
    沒有或跨日（快照過期）才退回 NOAA 天文計算——兩層都跟現實鎖死。"""
    if rise is not None and sset is not None and rise.date() == now.date():
        return rise, sset
    return sun_times(now.date(), lat, lon, now.tzinfo)


def _band(now, rise, sset, w: int) -> "pygame.Surface":
    if rise is None:
        rise_m, set_m = -9999.0, -9999.0             # 極夜：整條夜色
    else:
        rise_m = rise.hour * 60 + rise.minute
        set_m = sset.hour * 60 + sset.minute
    # key 含日出日落分鐘：開機後天氣快照抵達、API 真值取代計算值時自動重烤
    key = (now.date().isoformat(), theme.current_theme(), w, rise_m, set_m)
    s = _cache.get(key)
    if s is not None:
        return s
    _cache.clear()                                   # 只留當天當前參數這一筆
    pal = _phase_colors()
    s = pygame.Surface((w, BAND_H))
    for x in range(w):
        col = _color_at(x / w * 1440.0, rise_m, set_m, pal)
        pygame.draw.line(s, col, (x, 0), (x, BAND_H - 1))
    # 日出/日落刻痕：亮一階的 1px 豎線
    tick = _lerp(pal["twilight"], (255, 255, 255), 0.35)
    for m in (rise_m, set_m):
        if 0 <= m <= 1440:
            tx = round(m / 1440.0 * w)
            pygame.draw.line(s, tick, (tx, 0), (tx, BAND_H - 1))
    _cache[key] = s
    return s


def draw(surface, now, lat: float, lon: float, rise=None, sset=None) -> None:
    """畫在一切之後（top overlay）。now 帶 tzinfo；rise/sset 傳入天氣快照的
    open-meteo 當日真值（可 None，見 _resolve 的來源決策）。"""
    w = surface.get_width()
    rise, sset = _resolve(now, lat, lon, rise, sset)
    surface.blit(_band(now, rise, sset, w), (0, 0))
    # 「現在」光點：白晝金太陽、夜間冷白月亮，各帶一圈淡暈
    is_day = rise is not None and rise <= now <= sset
    x = round((now.hour * 60 + now.minute) / 1440.0 * w)
    cy = BAND_H // 2
    if is_day:
        core, halo = (255, 214, 96), (255, 190, 70)
    else:
        core, halo = (226, 230, 244), (150, 160, 200)
    pygame.draw.circle(surface, _lerp(halo, _phase_colors()["night"], 0.35),
                       (x, cy), 5)
    pygame.draw.circle(surface, core, (x, cy), 3)
