from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from deskbar import weather


class FakeResp:
    status_code = 200

    def json(self):
        return {"current": {"temperature_2m": 32.7, "weather_code": 53},
                "daily": {"temperature_2m_max": [35.2], "temperature_2m_min": [27.1],
                          "sunrise": ["2026-08-05T05:15:00"], "sunset": ["2026-08-05T18:35:00"]}}


def test_fetch_weather_parses():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    w = weather.fetch_weather(25.0, 121.5, "台北", http_get=lambda *a, **k: FakeResp(),
                              now_fn=lambda: now, metar_station="")
    assert w.temp == 32.7 and w.code == 53
    assert w.tmax == 35.2 and w.tmin == 27.1
    assert w.label == "台北" and w.fetched_at == now
    assert w.observed is False


def test_code_text_mapping():
    assert weather.code_text(0) == "晴"
    assert weather.code_text(2) == "多雲"
    assert weather.code_text(61) == "雨"
    assert weather.code_text(95) == "雷雨"
    assert weather.code_text(999) == "—"


def test_hybrid_weather_metar_fresh():
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2026, 8, 5, 13, 0, tzinfo=tz)
    metar_time = now - timedelta(minutes=20)  # 20 分鐘前（新鮮）

    def fake_metar(station):
        return {"temp": 35.0, "code": 1, "observed_at": metar_time, "raw": "METAR RCSS ..."}

    w = weather.fetch_weather(
        25.0, 121.5, "台北",
        http_get=lambda *a, **k: FakeResp(),
        now_fn=lambda: now,
        metar_station="RCSS",
        fetch_metar_fn=fake_metar,
    )
    # temp/code 用 METAR
    assert w.temp == 35.0
    assert w.code == 1
    # tmax/tmin/sunrise/sunset 用 Open-Meteo
    assert w.tmax == 35.2
    assert w.tmin == 27.1
    assert w.sunrise == datetime(2026, 8, 5, 5, 15, tzinfo=tz)
    assert w.sunset == datetime(2026, 8, 5, 18, 35, tzinfo=tz)
    assert w.observed is True


def test_hybrid_weather_metar_returns_none():
    now = datetime(2026, 8, 5, 13, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    w = weather.fetch_weather(
        25.0, 121.5, "台北",
        http_get=lambda *a, **k: FakeResp(),
        now_fn=lambda: now,
        metar_station="RCSS",
        fetch_metar_fn=lambda station: None,
    )
    # 全部沿用 Open-Meteo
    assert w.temp == 32.7
    assert w.code == 53
    assert w.observed is False


def test_hybrid_weather_metar_stale():
    tz = ZoneInfo("Asia/Taipei")
    now = datetime(2026, 8, 5, 13, 0, tzinfo=tz)
    stale_time = now - timedelta(hours=3)  # 3 小時前（超過 90 分鐘上限）

    def fake_metar(station):
        return {"temp": 35.0, "code": 1, "observed_at": stale_time, "raw": "METAR RCSS ..."}

    w = weather.fetch_weather(
        25.0, 121.5, "台北",
        http_get=lambda *a, **k: FakeResp(),
        now_fn=lambda: now,
        metar_station="RCSS",
        fetch_metar_fn=fake_metar,
    )
    # 太舊退回 Open-Meteo
    assert w.temp == 32.7
    assert w.code == 53
    assert w.observed is False


def test_hybrid_weather_metar_disabled():
    now = datetime(2026, 8, 5, 13, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    called = False

    def fake_metar(station):
        nonlocal called
        called = True
        return {"temp": 35.0, "code": 1, "observed_at": now}

    w = weather.fetch_weather(
        25.0, 121.5, "台北",
        http_get=lambda *a, **k: FakeResp(),
        now_fn=lambda: now,
        metar_station="",    # 空字串停用 METAR
        fetch_metar_fn=fake_metar,
    )
    assert not called
    assert w.temp == 32.7
    assert w.code == 53
    assert w.observed is False
