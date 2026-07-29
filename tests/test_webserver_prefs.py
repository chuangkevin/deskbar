"""/api/prefs：手機網頁調整裝置偏好（上下班時間/亮度/在場感應/同步頻率）。
GET 回全欄位、PATCH 白名單＋範圍驗證＋持久化、未接 settings 時 501。"""
from __future__ import annotations

import threading

import pytest

from deskbar.config import Settings
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


def test_patch_prefs_applies_and_saves(client):
    r = client.patch("/api/prefs", json={
        "work_end_min": 1170, "brightness_night": 20,
        "presence_enabled": True, "presence_interval_sec": 15,
        "presence_grace_sec": 45, "sync_interval_min": 10})
    assert r.status_code == 200
    s = client._settings
    assert s.work_end_min == 1170 and s.brightness_night == 20
    assert s.presence_enabled is True and s.presence_interval_sec == 15
    assert s.presence_grace_sec == 45 and s.sync_interval_min == 10
    assert client._saved, "PATCH 必須持久化"


@pytest.mark.parametrize("payload,why", [
    ({"work_end_min": 2000}, "超出範圍"),
    ({"brightness_day": 5}, "低於下限"),
    ({"presence_enabled": "yes"}, "型別錯誤"),
    ({"theme": "light"}, "theme 不開放（webserver 執行緒不得清渲染快取）"),
    ({"nonsense": 1}, "未知欄位"),
    ({}, "空 payload"),
])
def test_patch_prefs_rejects_bad_input_without_side_effects(client, payload, why):
    before = (client._settings.work_end_min, client._settings.brightness_day)
    r = client.patch("/api/prefs", json=payload)
    assert r.status_code == 400, why
    assert (client._settings.work_end_min, client._settings.brightness_day) == before
    assert not client._saved, "驗證失敗不得寫檔"


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
