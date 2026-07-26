from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

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


def code_text(code: int) -> str:
    for (lo, hi), txt in _CODES:
        if lo <= code <= hi:
            return txt
    return "—"


def fetch_weather(lat: float, lon: float, label: str, http_get=requests.get,
                  now_fn=lambda: datetime.now(ZoneInfo("Asia/Taipei"))) -> Weather:
    resp = http_get(URL, params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Taipei", "forecast_days": 1,
    }, timeout=20)
    body = resp.json()
    return Weather(
        temp=float(body["current"]["temperature_2m"]),
        code=int(body["current"]["weather_code"]),
        tmax=float(body["daily"]["temperature_2m_max"][0]),
        tmin=float(body["daily"]["temperature_2m_min"][0]),
        label=label,
        fetched_at=now_fn(),
    )
