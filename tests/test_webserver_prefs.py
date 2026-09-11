"""/api/prefs：手機網頁調整裝置偏好（上下班時間/亮度/在場感應/同步頻率）。
GET 回全欄位、PATCH 白名單＋範圍驗證＋持久化、未接 settings 時 501。"""
from __future__ import annotations

import threading

import pytest

from deskbar.config import SCENE_KEYS, Settings
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    saved = []
    app = create_app(_FakeStore(), settings_provider=settings,
                     settings_lock=threading.Lock(),
                     on_save=lambda s: saved.append(1))
    app.config["TESTING"] = True
    c = app.test_client()
    c._settings = settings
    c._saved = saved
    return c


def test_get_prefs_returns_all_fields(client):
    r = client.get("/api/prefs")
    assert r.status_code == 200
    d = r.get_json()
    assert d["work_start_min"] == 540 and d["work_end_min"] == 1080
    assert d["brightness_day"] == 100 and d["brightness_night"] == 40
    assert d["presence_enabled"] is False
    assert d["presence_interval_sec"] == 45 and d["sync_interval_min"] == 5
    assert d["presence_source"] == "bluetooth"
    assert d["presence_push_ttl_sec"] == 900
    assert d["usage_sources"] == ["claude", "antigravity", "openai", "cursor", "opencode"]
    assert d["pet_enabled"] is True


def test_phone_settings_lists_every_scene(client):
    html = client.get("/").get_data(as_text=True)
    missing = [key for key in SCENE_KEYS if f'["{key}",' not in html]
    assert missing == []
    assert '["planet_horizon","行星地平線"]' in html
    assert '["sisi","喜喜"]' not in html
    assert "小喜喜桌面寵物" in html


def test_phone_settings_escapes_weather_label_in_template(client):
    html = client.get("/").get_data(as_text=True)
    assert 'const weatherLabel=esc(p.weather_label||"—");' in html
    assert '目前：${p.weather_label||"—"}' not in html


def test_patch_prefs_applies_and_saves(client):
    r = client.patch("/api/prefs", json={
        "work_end_min": 1170, "brightness_night": 20,
        "presence_enabled": True, "presence_interval_sec": 30,
        "presence_grace_sec": 45, "sync_interval_min": 10,
        "presence_source": "push", "presence_push_ttl_sec": 600,
        "pet_enabled": False})
    assert r.status_code == 200
    s = client._settings
    assert s.work_end_min == 1170 and s.brightness_night == 20
    assert s.presence_enabled is True and s.presence_interval_sec == 30
    assert s.presence_grace_sec == 45 and s.sync_interval_min == 10
    assert s.presence_source == "push" and s.presence_push_ttl_sec == 600
    assert s.pet_enabled is False
    assert client._saved, "PATCH 必須持久化"


def test_usage_sources_allows_empty_and_rejects_invalid_without_save(client):
    assert client.patch("/api/prefs", json={"usage_sources": ["openai"]}).status_code == 200
    assert client._settings.usage_sources == ("openai",)
    before_saves = len(client._saved)
    for value in ("openai", ["unknown"], [True], {"openai": True}):
        assert client.patch("/api/prefs", json={"usage_sources": value}).status_code == 400
    assert len(client._saved) == before_saves
    assert client.patch("/api/prefs", json={"usage_sources": []}).status_code == 200
    assert client._settings.usage_sources == ()


@pytest.mark.parametrize("payload,why", [
    ({"work_end_min": 2000}, "超出範圍"),
    ({"brightness_day": 5}, "低於下限"),
    ({"presence_enabled": "yes"}, "型別錯誤"),
    ({"theme": "light"}, "theme 不開放（webserver 執行緒不得清渲染快取）"),
    ({"nonsense": 1}, "未知欄位"),
    ({}, "空 payload"),
    ({"presence_interval_sec": 5}, "presence_interval_sec 下限為 20"),
    ({"presence_interval_sec": 19}, "presence_interval_sec 下限為 20"),
    ({"presence_push_ttl_sec": 59}, "presence_push_ttl_sec 下限為 60"),
    ({"presence_push_ttl_sec": 86401}, "presence_push_ttl_sec 上限為 86400"),
    ({"presence_source": "invalid"}, "presence_source 只收 bluetooth 或 push"),
])
def test_patch_prefs_rejects_bad_input_without_side_effects(client, payload, why):
    before = (client._settings.work_end_min, client._settings.brightness_day)
    r = client.patch("/api/prefs", json=payload)
    assert r.status_code == 400, why
    assert (client._settings.work_end_min, client._settings.brightness_day) == before
    assert not client._saved, "驗證失敗不得寫檔"


def test_presence_interval_20_accepted(client):
    r = client.patch("/api/prefs", json={"presence_interval_sec": 20})
    assert r.status_code == 200
    assert client._settings.presence_interval_sec == 20


def test_patch_linear_key_sets_value_and_get_only_exposes_bool(client):
    r = client.patch("/api/prefs", json={"linear_api_key": " lin_api_secret123 "})
    assert r.status_code == 200
    assert client._settings.linear_api_key == "lin_api_secret123", "應 strip 後寫入"
    d = client.get("/api/prefs").get_json()
    assert d["linear_key_set"] is True
    assert "lin_api_secret123" not in str(d), "金鑰原文絕不得出現在 GET 回應"
    r2 = client.patch("/api/prefs", json={"linear_api_key": "x" * 300})
    assert r2.status_code == 400, "超長金鑰拒收"
    r3 = client.patch("/api/prefs", json={"linear_api_key": ""})
    assert r3.status_code == 200 and client._settings.linear_api_key == "", "空字串=清除"


def test_prefs_unavailable_without_settings_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    app = create_app(_FakeStore())
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.get("/api/prefs").status_code == 501
    assert c.patch("/api/prefs", json={"brightness_day": 50}).status_code == 501
