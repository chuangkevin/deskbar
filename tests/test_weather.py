from datetime import datetime
from zoneinfo import ZoneInfo
from deskbar import weather


class FakeResp:
    status_code = 200

    def json(self):
        return {"current": {"temperature_2m": 33.4, "weather_code": 80},
                "daily": {"temperature_2m_max": [34.1], "temperature_2m_min": [26.3]}}


def test_fetch_weather_parses():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    w = weather.fetch_weather(25.0, 121.5, "台北", http_get=lambda *a, **k: FakeResp(),
                              now_fn=lambda: now)
    assert w.temp == 33.4 and w.code == 80
    assert w.tmax == 34.1 and w.tmin == 26.3
    assert w.label == "台北" and w.fetched_at == now


def test_code_text_mapping():
    assert weather.code_text(0) == "晴"
    assert weather.code_text(2) == "多雲"
    assert weather.code_text(61) == "雨"
    assert weather.code_text(95) == "雷雨"
    assert weather.code_text(999) == "—"
