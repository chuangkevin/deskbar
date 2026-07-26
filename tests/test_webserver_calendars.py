import threading

import pytest

from deskbar.config import Settings
from deskbar.webserver import create_app


def _settings_with_account():
    settings = Settings()
    acc = settings.ensure_account("alice@example.com")
    acc.lane_label = "小家"
    acc.calendars["cal1"] = True
    acc.calendars["cal2"] = False
    return settings


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    (accounts_dir / "alice.json").write_text(
        '{"email": "alice@example.com", "refresh_token": "fake-refresh-token", '
        '"client_id": "fake-client-id", "client_secret": "fake-client-secret", '
        '"calendars": [{"id": "cal1", "summary": "公司行事曆", "primary": true}]}',
        encoding="utf-8",
    )
    settings = _settings_with_account()
    lock = threading.Lock()
    saved = []
    app = create_app(object(), settings_provider=settings, settings_lock=lock,
                      on_save=saved.append)
    return app.test_client(), settings, saved


def test_calendars_get_structure(app_ctx):
    """summary 從 token 檔查得到就用 token 的，查不到就 fallback 成 id（cal2）。"""
    client, _settings, _saved = app_ctx
    r = client.get("/api/calendars")
    assert r.status_code == 200
    assert r.get_json() == [{
        "account": "alice@example.com",
        "lane_label": "小家",
        "calendars": [
            {"id": "cal1", "summary": "公司行事曆", "enabled": True},
            {"id": "cal2", "summary": "cal2", "enabled": False},
        ],
    }]


def test_calendars_patch_updates_value_and_calls_on_save(app_ctx):
    client, settings, saved = app_ctx
    r = client.patch("/api/calendars", json={
        "account": "alice@example.com", "calendar_id": "cal2", "enabled": True,
    })
    assert r.status_code == 200
    assert settings.accounts["alice@example.com"].calendars["cal2"] is True
    assert saved and saved[-1] is settings


def test_calendars_patch_unknown_account_404(app_ctx):
    client, _settings, _saved = app_ctx
    r = client.patch("/api/calendars", json={
        "account": "nobody@example.com", "calendar_id": "cal1", "enabled": True,
    })
    assert r.status_code == 404


def test_calendars_patch_unknown_calendar_404(app_ctx):
    client, _settings, _saved = app_ctx
    r = client.patch("/api/calendars", json={
        "account": "alice@example.com", "calendar_id": "nope", "enabled": True,
    })
    assert r.status_code == 404


def test_calendars_patch_enabled_not_bool_400(app_ctx):
    client, _settings, _saved = app_ctx
    r = client.patch("/api/calendars", json={
        "account": "alice@example.com", "calendar_id": "cal1", "enabled": "yes",
    })
    assert r.status_code == 400


def test_calendars_without_settings_wiring_returns_501(tmp_path, monkeypatch):
    """create_app 未接 settings_provider/settings_lock/on_save 時，兩個 API 都回 501。"""
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    client = create_app(object()).test_client()
    assert client.get("/api/calendars").status_code == 501
    assert client.patch("/api/calendars", json={}).status_code == 501
