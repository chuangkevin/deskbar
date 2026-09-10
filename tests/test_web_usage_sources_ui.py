"""Checks for settings-page OpenAI account alias controls and prefs wiring."""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deskbar import config
from deskbar.claudeusage import OaAccount, UsageInfo
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 9, 10, 16, 0, tzinfo=TZ)


def _html() -> str:
    return (Path(__file__).parent.parent / "deskbar" / "web" / "index.html").read_text(encoding="utf-8")


class _FakeStore:
    def list(self):
        return []


@pytest.fixture
def prefs_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    saved = []
    app = create_app(_FakeStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: saved.append(1))
    app.config["TESTING"] = True
    client = app.test_client()
    client._settings = settings
    client._saved = saved
    return client


def test_openai_alias_block_renders_only_when_seen_accounts_exist():
    content = _html()
    assert "OpenAI 帳號別名" in content
    assert "oa_accounts_seen" in content
    assert "oa_aliases" in content
    assert "oaAccounts.length?" in content
    assert "</fieldset>`:\"\"" in content


def test_openai_alias_inputs_follow_mobile_and_touch_contract():
    content = _html()
    assert 'class="p_oa_alias"' in content
    assert 'maxlength="24"' in content
    assert 'placeholder="不填就用預設名稱"' in content
    assert ".oa-alias-row" in content
    assert "min-height:44px" in content
    assert "max-width:100%;overflow-x:hidden" in content
    assert "@media(max-width:767px)" in content


def test_save_prefs_includes_openai_aliases_from_inputs():
    content = _html()
    assert 'document.querySelectorAll(".p_oa_alias")' in content
    assert "Object.fromEntries" in content
    assert "i.dataset.accountId" in content


def test_oa_aliases_roundtrip_and_invalid_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"oa_aliases": {" acct-a ": " SYSTEMCOM ", "acct-b": ""}}),
        encoding="utf-8")
    settings = config.load_settings()
    assert settings.oa_aliases == {"acct-a": "SYSTEMCOM"}
    config.save_settings(settings)
    assert config.load_settings().oa_aliases == {"acct-a": "SYSTEMCOM"}

    (tmp_path / "settings.json").write_text(
        json.dumps({"oa_aliases": {"acct-a": "x" * 25}}), encoding="utf-8")
    assert config.load_settings().oa_aliases == {}


def test_get_prefs_returns_openai_aliases_and_seen_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings(oa_aliases={"acct-a": "SYSTEMCOM"})
    state = AppState()
    state.set_usage(UsageInfo(
        session_pct=None, session_resets_at=None,
        weekly_pct=None, weekly_resets_at=None,
        fable_pct=None, fable_resets_at=None,
        fetched_at=NOW,
        oa_accounts=(
            OaAccount("acct-a", "kevin.systemcom", 100.0, NOW + timedelta(days=5), NOW),
            OaAccount("acct-b", "kevin.dev01", 18.0, NOW + timedelta(days=6), NOW),
        ),
    ))
    app = create_app(_FakeStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: None,
                     usage_state=state)
    app.config["TESTING"] = True
    data = app.test_client().get("/api/prefs").get_json()
    assert data["oa_aliases"] == {"acct-a": "SYSTEMCOM"}
    assert data["oa_accounts_seen"] == [
        {"account_id": "acct-a", "name": "kevin.systemcom"},
        {"account_id": "acct-b", "name": "kevin.dev01"},
    ]


def test_get_prefs_returns_empty_openai_alias_defaults(prefs_client):
    data = prefs_client.get("/api/prefs").get_json()
    assert data["oa_aliases"] == {}
    assert data["oa_accounts_seen"] == []


def test_oa_aliases_post_stores_reads_and_clears_aliases(prefs_client):
    response = prefs_client.post("/api/prefs", json={"oa_aliases": {
        " acct-a ": " SYSTEMCOM ",
        "acct-b": "DEV01",
    }})
    assert response.status_code == 200
    assert prefs_client._settings.oa_aliases == {"acct-a": "SYSTEMCOM", "acct-b": "DEV01"}
    assert prefs_client.get("/api/prefs").get_json()["oa_aliases"] == {
        "acct-a": "SYSTEMCOM",
        "acct-b": "DEV01",
    }

    response = prefs_client.post("/api/prefs", json={"oa_aliases": {"acct-a": ""}})
    assert response.status_code == 200
    assert prefs_client._settings.oa_aliases == {"acct-b": "DEV01"}


@pytest.mark.parametrize("value", [
    "not-an-object",
    {"": "SYSTEMCOM"},
    {"acct-a": 123},
    {"acct-a": "x" * 25},
    {str(i): "alias" for i in range(9)},
])
def test_oa_aliases_rejects_invalid_input_without_save(prefs_client, value):
    prefs_client._settings.oa_aliases = {"acct-a": "SYSTEMCOM"}
    before_saves = len(prefs_client._saved)
    response = prefs_client.post("/api/prefs", json={"oa_aliases": value})
    assert response.status_code == 400
    assert prefs_client._settings.oa_aliases == {"acct-a": "SYSTEMCOM"}
    assert len(prefs_client._saved) == before_saves


def test_oa_accounts_seen_post_is_ignored_without_writing_settings(prefs_client):
    response = prefs_client.post("/api/prefs", json={"oa_accounts_seen": [
        {"account_id": "acct-a", "name": "should-not-save"},
    ]})
    assert response.status_code == 200
    assert not hasattr(prefs_client._settings, "oa_accounts_seen")
    assert prefs_client._settings.oa_aliases == {}
    assert prefs_client._saved == []
