import re
from datetime import datetime
from zoneinfo import ZoneInfo

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_USAGE_TZ = ZoneInfo("Asia/Taipei")
_PCT_FIELDS = ("session_pct", "weekly_pct", "fable_pct", "ag_5h_pct", "ag_weekly_pct", "oa_weekly_pct")
_RESETS_FIELDS = ("session_resets_at", "weekly_resets_at", "fable_resets_at", "ag_5h_resets_at", "ag_weekly_resets_at", "oa_weekly_resets_at")
_USAGE_FETCHED_FIELDS = ("fetched_at", "claude_fetched_at", "ag_fetched_at", "oa_fetched_at")

# 手機網頁可調的裝置偏好（2026-07-27 需求：「那些設定也應該要可以在手機
# 設定頁調整」）。theme 刻意不開放——theme.set_theme 會清渲染快取，只能由
# UI 執行緒自己做，webserver 執行緒碰了會跟 render 撞快取。
# 2026-08-04 實機事故：presence_interval_sec 下限由 5 改為 20 秒——單次探測
# 最壞 10 秒，間隔比它短等於保證重疊送連線請求，會把 BCM43438 控制器打死。
_PREF_INT = {
    "work_start_min": (0, 1410), "work_end_min": (0, 1410),
    "brightness_day": (10, 100), "brightness_night": (10, 100),
    "sleep_start_min": (0, 1410), "sleep_end_min": (0, 1410),
    "presence_interval_sec": (20, 600), "presence_grace_sec": (0, 3600),
    "presence_push_ttl_sec": (60, 86400),
    "sync_interval_min": (1, 120),
}
_PREF_BOOL = {"presence_enabled", "sleep_enabled", "weather_auto_locate",
              "pet_enabled"}
_PREF_STR = {"linear_api_key": 200,      # 值=長度上限；GET 絕不回傳 key 原文
             "weather_label": 12,
             "weather_metar_station": 8}
# 手動指定城市（IP 定位在雙北常差一個行政區——ISP 登記地 ≠ 實際位置）：
# 網頁用 Open-Meteo geocoding 查好座標後直接寫入，並關掉自動定位
_PREF_FLOAT = {"weather_lat": (-90.0, 90.0), "weather_lon": (-180.0, 180.0)}


def _valid_pct(v) -> bool:
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    return 0 <= v <= 100


def _valid_resets_at(v) -> bool:
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _parse_dt(v):
    return None if v is None else datetime.fromisoformat(v.replace("Z", "+00:00"))


def _to_float(v):
    return None if v is None else float(v)
