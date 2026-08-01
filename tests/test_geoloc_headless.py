"""IP 定位：geoloc.locate 解析/失敗容錯、weather_sync_once 自動跟隨位置
（改寫 settings＋持久化＋用新座標打天氣）、關閉開關即不查。"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from deskbar import geoloc
from deskbar.config import Settings, load_settings
from deskbar.store import AppState
from deskbar.sync import SyncDeps, weather_sync_once

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 30, 22, 0, tzinfo=TZ)


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_locate_parses_and_caps_label():
    def fake_get(url, params=None, timeout=None):
        assert "ip-api.com" in url and params["lang"] == "zh-TW"
        return _Resp({"status": "success", "lat": 24.99, "lon": 121.30,
                      "city": "桃園市中壢區某某里超長名稱", "regionName": "桃園市"})
    lat, lon, label = geoloc.locate(http_get=fake_get)
    assert (lat, lon) == (24.99, 121.30)
    assert label == "桃園市中壢區某某里超長名稱"[:12]


def test_locate_maps_taiwan_english_city_names():
    def fake_get(url, params=None, timeout=None):
        return _Resp({"status": "success", "lat": 25.07, "lon": 121.46,
                      "city": "New Taipei City"})
    assert geoloc.locate(http_get=fake_get)[2] == "新北", \
        "ip-api zh-TW 對台灣城市常缺漏，常見城市要對照成中文"


def test_locate_failure_paths_return_none():
    assert geoloc.locate(http_get=lambda *a, **k: _Resp({"status": "fail"})) is None

    def boom(*a, **k):
        raise OSError("no network")
    assert geoloc.locate(http_get=boom) is None


def _deps(geo_payload):
    def fake_get(url, params=None, timeout=None):
        if "ip-api.com" in url:
            return _Resp(geo_payload)
        # open-meteo：回傳可辨識溫度，並把收到的座標塞進 temp 供驗證
        return _Resp({"current": {"temperature_2m": params["latitude"],
                                  "weather_code": 3},
                      "daily": {"temperature_2m_max": [30.0],
                                "temperature_2m_min": [25.0]}})
    return SyncDeps(http_get=fake_get, now_fn=lambda: NOW, tz=TZ,
                    today_fn=lambda: NOW.date(), http_post=None)


def test_weather_sync_auto_locates_updates_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings()          # 預設台北 25.046 / weather_auto_locate=True
    state = AppState()
    deps = _deps({"status": "success", "lat": 24.99, "lon": 121.30, "city": "桃園"})
    weather_sync_once(state, s, deps, threading.Lock())
    assert (s.weather_lat, s.weather_lon, s.weather_label) == (24.99, 121.30, "桃園")
    w = state.snapshot().weather
    assert w is not None and w.temp == 24.99, "要用新座標打天氣"
    assert w.label == "桃園"
    s2 = load_settings()
    assert s2.weather_label == "桃園", "位置變更要持久化"


def test_weather_sync_auto_locate_skips_small_move(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings()
    state = AppState()
    deps = _deps({"status": "success", "lat": 25.05, "lon": 121.52, "city": "台北"})
    weather_sync_once(state, s, deps, threading.Lock())
    assert s.weather_lat == 25.046, "5km 內不追著 IP 微調（避免 label/座標抖動）"


def test_weather_sync_respects_auto_locate_off(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings()
    s.weather_auto_locate = False
    state = AppState()
    called = []

    def fake_get(url, params=None, timeout=None):
        called.append(url)
        assert "ip-api.com" not in url, "關閉自動定位就不准查 IP"
        return _Resp({"current": {"temperature_2m": 30.0, "weather_code": 0},
                      "daily": {"temperature_2m_max": [31.0],
                                "temperature_2m_min": [25.0]}})
    weather_sync_once(state, s, SyncDeps(http_get=fake_get, now_fn=lambda: NOW,
                                         tz=TZ, today_fn=lambda: NOW.date(),
                                         http_post=None), threading.Lock())
    assert s.weather_lat == 25.046 and called, "座標不動、天氣照打"
