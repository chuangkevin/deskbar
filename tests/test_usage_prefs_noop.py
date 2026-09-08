from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


def _app(tmp_path, monkeypatch, *, settings=None):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DESKBAR_PUSH_TOKEN", raising=False)
    state = AppState(tmp_path / "usage_sources.json")
    settings = settings or Settings()
    saves = []

    def save(settings_provider):
        saves.append(tuple(settings_provider.usage_sources))

    app = create_app(
        _FakeStore(),
        settings_provider=settings,
        settings_lock=threading.Lock(),
        on_save=save,
        usage_state=state,
    )
    app.config["TESTING"] = True
    return app, state, settings, saves


def _client(app):
    return app.test_client()


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _legacy_payload() -> dict:
    return {
        "fetched_at": _iso(10),
        "weekly_pct": 21,
        "ag_weekly_pct": 31,
        "oa_weekly_pct": 41,
    }


def _source(state: AppState, source_id: str) -> dict:
    return next(
        item
        for item in state.list_usage_sources(include_archived=True)
        if item["source_id"] == source_id
    )


def _make_legacy_sources(app):
    assert _client(app).post("/api/usage", json=_legacy_payload()).status_code == 204


@pytest.mark.parametrize(
    ("extra_payload", "expected_sync_interval"),
    [
        ({}, 5),
        ({"sync_interval_min": 10}, 10),
    ],
    ids=["single-field", "multi-field"],
)
def test_identical_usage_sources_save_preserves_manual_pause_and_named_account(
    tmp_path,
    monkeypatch,
    extra_payload,
    expected_sync_interval,
):
    app, state, settings, saves = _app(tmp_path, monkeypatch)
    _make_legacy_sources(app)
    state.update_usage_source("legacy-claude", {"enabled": False, "visible": False})
    named = state.create_usage_source(
        {
            "provider": "claude",
            "provider_account_id": "team@example.com",
            "display_name": "Team Claude",
        }
    )
    before_named = json.dumps(_source(state, named["source_id"]), sort_keys=True)

    payload = {"usage_sources": list(settings.usage_sources), **extra_payload}
    response = _client(app).patch("/api/prefs", json=payload)

    assert response.status_code == 200
    assert settings.usage_sources == ("claude", "antigravity", "openai")
    assert settings.sync_interval_min == expected_sync_interval
    assert saves == [("claude", "antigravity", "openai")]
    claude = _source(state, "legacy-claude")
    assert claude["enabled"] is False
    assert claude["visible"] is False
    assert json.dumps(_source(state, named["source_id"]), sort_keys=True) == before_named
