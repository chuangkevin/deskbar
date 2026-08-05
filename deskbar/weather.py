from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from deskbar.metar import DEFAULT_STATION, STALE_AFTER_S, fetch_metar

URL = "https://api.open-meteo.com/v1/forecast"
_CODES = [
    ((0, 0), "晴"), ((1, 1), "晴時多雲"), ((2, 2), "多雲"), ((3, 3), "陰"),
    ((45, 48), "霧"), ((51, 57), "毛毛雨"), ((61, 67), "雨"), ((71, 77), "雪"),
    ((80, 82), "陣雨"), ((85, 86), "雪"), ((95, 99), "雷雨"),
]


@dataclass(frozen=True)
class Weather:
    temp: float
    code: int
    tmax: float
    tmin: float
    label: str
    fetched_at: datetime
    sunrise: "datetime | None" = None    # open-meteo 當日實際日出（日光儀優先用
    sunset: "datetime | None" = None     # API 真值；斷網才退回天文計算）
    observed: bool = False               # True＝現況來自 METAR 實測，False＝Open-Meteo 模式推算


def code_text(code: int) -> str:
    for (lo, hi), txt in _CODES:
        if lo <= code <= hi:
            return txt
    return "—"


def fetch_weather(lat: float, lon: float, label: str, http_get=requests.get,
                  now_fn=lambda: datetime.now(ZoneInfo("Asia/Taipei")),
                  metar_station: str = DEFAULT_STATION,
                  fetch_metar_fn=None) -> Weather:
    """抓取天氣資料。

    2026-08-05 實測案例：數值預報模式常在午後局部對流時誤報毛毛雨，
    故現況（現溫 temp、天氣碼 code）優先採用 METAR 氣象站實測觀測；
    預報（高低溫 tmax/tmin、日出日落 sunrise/sunset）則維持 Open-Meteo。
    若 METAR 抓取失敗或資料過期（> STALE_AFTER_S），則優雅退回純 Open-Meteo 模式。
    """
    resp = http_get(URL, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "timezone": "Asia/Taipei", "forecast_days": 1,
    }, timeout=20)
    body = resp.json()
    tz = ZoneInfo("Asia/Taipei")

    def _iso(key):
        try:
            return datetime.fromisoformat(body["daily"][key][0]).replace(tzinfo=tz)
        except (KeyError, IndexError, TypeError, ValueError):
            return None                  # API 沒給就留 None，日光儀退天文計算

    temp = float(body["current"]["temperature_2m"])
    code = int(body["current"]["weather_code"])
    observed = False

    if metar_station:
        fn = fetch_metar_fn if fetch_metar_fn is not None else lambda s: fetch_metar(s, http_get=http_get)
        try:
            m_res = fn(metar_station)
            if m_res and "temp" in m_res and "code" in m_res and "observed_at" in m_res:
                obs_at = m_res["observed_at"]
                now_dt = now_fn()
                age = (now_dt - obs_at).total_seconds()
                if 0 <= age <= STALE_AFTER_S:
                    temp = float(m_res["temp"])
                    code = int(m_res["code"])
                    observed = True
        except Exception:
            pass

    return Weather(
        temp=temp,
        code=code,
        tmax=float(body["daily"]["temperature_2m_max"][0]),
        tmin=float(body["daily"]["temperature_2m_min"][0]),
        label=label,
        fetched_at=now_fn(),
        sunrise=_iso("sunrise"),
        sunset=_iso("sunset"),
        observed=observed,
    )

