"""螢幕亮度排程：上班時段用日間亮度、其餘時段用下班亮度。

這塊 HDMI 面板沒有可控背光（/sys/class/backlight 不存在），亮度用軟體疊黑
實現：App._flip() 在「旋轉/縮放後的輸出面」上蓋一層對應透明度的黑幕——
必須蓋在輸出面（每幀新建）而非 logical（持久畫布），蓋 logical 會讓氛圍幀
只重畫左欄時，其餘區域被逐幀重複疊黑、越來越暗。

全部純函式，好測。
"""
from __future__ import annotations


def in_work_span(minute_of_day: int, start_min: int, end_min: int) -> bool:
    """分鐘制（0-1439）。start == end 視為全天上班（永不變暗）；
    支援跨午夜（start > end）。"""
    if start_min == end_min:
        return True
    if start_min < end_min:
        return start_min <= minute_of_day < end_min
    return minute_of_day >= start_min or minute_of_day < end_min


def effective(settings, minute_of_day: int, awake: bool = False) -> int:
    """當下應套用的亮度百分比。0＝深夜熄屏（睡眠時段內且沒有觸摸喚醒）；
    其餘夾在 10..100。awake=True（觸摸喚醒中）時忽略睡眠時段。"""
    if (getattr(settings, "sleep_enabled", False) and not awake
            and in_work_span(minute_of_day, settings.sleep_start_min,
                             settings.sleep_end_min)):
        return 0
    if in_work_span(minute_of_day, settings.work_start_min, settings.work_end_min):
        pct = settings.brightness_day
    else:
        pct = settings.brightness_night
    return max(10, min(100, int(pct)))


def veil_alpha(pct: int) -> int:
    """亮度 → 疊黑 alpha。100% = 0（不疊）；10% ≈ alpha 229；
    0（熄屏）→ 255 全黑（觸摸喚醒 30 秒）。"""
    if pct <= 0:
        return 255
    pct = max(10, min(100, int(pct)))
    return round(255 * (1 - pct / 100))
