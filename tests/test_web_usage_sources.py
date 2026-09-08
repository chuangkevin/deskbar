from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


def _client(tmp_path, monkeypatch, *, state=None, settings=None):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DESKBAR_PUSH_TOKEN", raising=False)
    state = state or AppState(tmp_path / "usage_sources.json")
    kwargs = {"usage_state": state}
    saved = []
    if settings is not None:
        kwargs.update(
            settings_provider=settings,
            settings_lock=threading.Lock(),
            on_save=lambda _settings: saved.append(1),
        )
    app = create_app(_FakeStore(), **kwargs)
    app.config["TESTING"] = True
    client = app.test_client()
    client._saved = saved
    return client, state


def _observed_at(minutes_ago=5):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _obs(*, account=None, pct=33, minutes_ago=5):
    return {
        "provider_account_id": account,
        "observed_at": _observed_at(minutes_ago),
        "metrics": {"weekly": {"used_pct": pct}},
    }


def _null_legacy_payload():
    return {
        "session_pct": None,
        "session_resets_at": None,
        "weekly_pct": None,
        "weekly_resets_at": None,
        "fable_pct": None,
        "fable_resets_at": None,
        "ag_5h_pct": None,
        "ag_5h_resets_at": None,
        "ag_weekly_pct": None,
        "ag_weekly_resets_at": None,
        "oa_weekly_pct": None,
        "oa_weekly_resets_at": None,
    }


def _sources(state, *, include_archived=True):
    return state.list_usage_sources(include_archived=include_archived)


def _source(state, source_id):
    return next(item for item in _sources(state) if item["source_id"] == source_id)


def test_usage_source_management_roundtrip_persists_archive_restore(tmp_path, monkeypatch):
    path = tmp_path / "usage_sources.json"
    state = AppState(path)
    client, _ = _client(tmp_path, monkeypatch, state=state)

    first = client.post(
        "/api/usage-sources",
        json={"provider": "codex", "provider_account_id": "acct-a", "display_name": "Account A"},
    )
    second = client.post(
        "/api/usage-sources",
        json={"provider": "openai", "provider_account_id": "acct-b", "display_name": "Account B"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    a_id = first.get_json()["source"]["source_id"]
    b_id = second.get_json()["source"]["source_id"]
    assert first.get_json()["source"]["provider"] == "openai"

    edited = client.patch(
        f"/api/usage-sources/{a_id}",
        json={"display_name": "Renamed A", "order": 4, "selected_metrics": ["weekly"]},
    )
    assert edited.status_code == 200
    assert edited.get_json()["source"]["display_name"] == "Renamed A"

    archived = client.patch(f"/api/usage-sources/{b_id}", json={"archived": True})
    assert archived.status_code == 200
    assert b_id not in {item["source_id"] for item in client.get("/api/usage-sources").get_json()["sources"]}
    assert b_id in {
        item["source_id"]
        for item in client.get("/api/usage-sources?include_archived=1").get_json()["sources"]
    }

    restored = client.patch(f"/api/usage-sources/{b_id}", json={"archived": False})
    assert restored.status_code == 200

    reloaded = AppState(path)
    assert _source(reloaded, a_id)["display_name"] == "Renamed A"
    assert _source(reloaded, a_id)["selected_metrics"] == ["weekly"]
    assert _source(reloaded, b_id)["archived"] is False
    assert {item["source_id"] for item in reloaded.snapshot().usage_sources} == {a_id, b_id}


def test_source_tokens_are_secret_rotated_and_source_scoped(tmp_path, monkeypatch):
    state = AppState(tmp_path / "usage_sources.json")
    client, _ = _client(tmp_path, monkeypatch, state=state)
    a_id = client.post("/api/usage-sources", json={"provider": "custom", "display_name": "A"}).get_json()[
        "source"
    ]["source_id"]
    b_id = client.post("/api/usage-sources", json={"provider": "custom", "display_name": "B"}).get_json()[
        "source"
    ]["source_id"]

    token_a_response = client.post(f"/api/usage-sources/{a_id}/token")
    token_b_response = client.post(f"/api/usage-sources/{b_id}/token")
    token_a = token_a_response.get_json()["token"]
    token_b = token_b_response.get_json()["token"]
    assert token_a_response.headers["Cache-Control"] == "no-store"

    assert client.post(f"/api/usage-sources/{a_id}/observations", json=_obs()).status_code == 401
    assert client.post(
        f"/api/usage-sources/{a_id}/observations",
        headers={"X-Deskbar-Source-Token": "wrong"},
        json=_obs(),
    ).status_code == 401
    assert client.post(
        f"/api/usage-sources/{a_id}/observations",
        headers={"X-Deskbar-Source-Token": token_b},
        json=_obs(),
    ).status_code == 401

    accepted = client.post(
        f"/api/usage-sources/{a_id}/observations",
        headers={"X-Deskbar-Source-Token": token_a},
        json=_obs(pct=44),
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["accepted"] is True
    assert _source(state, a_id)["observation"]["metrics"]["weekly"]["used_pct"] == 44

    new_token = client.post(f"/api/usage-sources/{a_id}/token").get_json()["token"]
    assert client.post(
        f"/api/usage-sources/{a_id}/observations",
        headers={"X-Deskbar-Source-Token": token_a},
        json=_obs(pct=45, minutes_ago=4),
    ).status_code == 401
    assert client.post(
        f"/api/usage-sources/{a_id}/observations",
        headers={"X-Deskbar-Source-Token": new_token},
        json=_obs(pct=46, minutes_ago=3),
    ).status_code == 200

    listed = json.dumps(client.get("/api/usage-sources?include_archived=1").get_json(), sort_keys=True)
    assert token_a not in listed
    assert token_b not in listed
    assert new_token not in listed
    assert "sha256" not in listed.lower()


def test_management_auth_requires_push_token_even_with_same_origin_headers(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DESKBAR_PUSH_TOKEN", "push-secret")
    state = AppState(tmp_path / "usage_sources.json")
    app = create_app(_FakeStore(), usage_state=state)
    app.config["TESTING"] = True
    client = app.test_client()

    assert client.post(
        "/api/usage-sources",
        json={"provider": "custom", "display_name": "No token"},
    ).status_code == 401
    assert _sources(state) == []

    assert client.post(
        "/api/usage-sources",
        headers={"X-Deskbar-Token": "wrong"},
        json={"provider": "custom", "display_name": "Wrong token"},
    ).status_code == 401
    assert _sources(state) == []

    assert client.post(
        "/api/usage-sources",
        headers={"X-Deskbar-Token": "push-secret"},
        json={"provider": "custom", "display_name": "Agent"},
    ).status_code == 201

    # Origin/Referer only pass the CSRF gate; they are not management auth.
    assert client.post(
        "/api/usage-sources",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "http://deskbar.local:8080"},
        json={"provider": "custom", "display_name": "Phone"},
    ).status_code == 401

    assert client.post(
        "/api/usage-sources",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "http://deskbar.local:8080", "X-Deskbar-Token": "push-secret"},
        json={"provider": "custom", "display_name": "Phone"},
    ).status_code == 201

    before = len(_sources(state))
    cross = client.post(
        "/api/usage-sources",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "https://evil.example", "X-Deskbar-Token": "push-secret"},
        json={"provider": "custom", "display_name": "Blocked"},
    )
    assert cross.status_code == 403
    assert len(_sources(state)) == before


def test_legacy_usage_bridge_preserves_flat_usage_and_rejects_invalid_account_before_mutation(
    tmp_path,
    monkeypatch,
):
    state = AppState(tmp_path / "usage_sources.json")
    client, _ = _client(tmp_path, monkeypatch, state=state)
    payload = {
        "fetched_at": "2026-08-04T01:23:45+00:00",
        "session_pct": 12.0,
        "session_resets_at": "2026-08-04T06:23:45Z",
        "weekly_pct": 34.0,
        "weekly_resets_at": "2026-08-11T00:00:00Z",
        "fable_pct": None,
        "fable_resets_at": None,
        "ag_5h_pct": None,
        "ag_5h_resets_at": None,
        "ag_weekly_pct": None,
        "ag_weekly_resets_at": None,
        "oa_account_id": "acct-a",
        "oa_weekly_pct": 56.0,
        "oa_weekly_resets_at": "2026-08-11T00:00:00Z",
    }

    assert client.post("/api/usage", json=payload).status_code == 204
    usage = state.snapshot().usage
    assert usage.session_pct == 12.0
    assert usage.oa_weekly_pct == 56.0
    account = next(item for item in _sources(state) if item["provider_account_id"] == "acct-a")
    assert account["provider"] == "openai"
    assert account["observation"]["metrics"]["weekly"]["used_pct"] == 56.0

    before_sources = json.dumps(_sources(state), sort_keys=True)
    before_usage = state.snapshot().usage
    bad = client.post("/api/usage", json={**payload, "oa_account_id": ""})
    assert bad.status_code == 400
    assert json.dumps(_sources(state), sort_keys=True) == before_sources
    assert state.snapshot().usage is before_usage


def test_legacy_all_null_payload_keeps_old_flat_behavior_without_registry_change(tmp_path, monkeypatch):
    state = AppState(tmp_path / "usage_sources.json")
    client, _ = _client(tmp_path, monkeypatch, state=state)

    assert client.post("/api/usage", json=_null_legacy_payload()).status_code == 204
    assert state.snapshot().usage is not None
    assert _sources(state) == []


def test_legacy_prefs_toggle_only_syncs_legacy_sources(tmp_path, monkeypatch):
    settings = Settings()
    state = AppState(tmp_path / "usage_sources.json")
    manual = state.create_usage_source(
        {"provider": "claude", "provider_account_id": "team@example.com", "display_name": "Team Claude"}
    )
    client, _ = _client(tmp_path, monkeypatch, state=state, settings=settings)
    assert client.post(
        "/api/usage",
        json={
            "fetched_at": "2026-08-04T01:23:45+00:00",
            "weekly_pct": 22.0,
            "weekly_resets_at": "2026-08-11T00:00:00Z",
        },
    ).status_code == 204

    assert client.patch("/api/prefs", json={"usage_sources": ["openai"]}).status_code == 200
    legacy = _source(state, "legacy-claude")
    named = _source(state, manual["source_id"])
    assert legacy["enabled"] is False
    assert legacy["visible"] is False
    assert named["enabled"] is True
    assert named["visible"] is True

    assert client.patch("/api/prefs", json={"usage_sources": ["claude", "openai"]}).status_code == 200
    legacy = _source(state, "legacy-claude")
    assert legacy["enabled"] is True
    assert legacy["visible"] is True


def test_unknown_disabled_archived_and_corrupted_registry_paths(tmp_path, monkeypatch):
    path = tmp_path / "usage_sources.json"
    state = AppState(path)
    client, _ = _client(tmp_path, monkeypatch, state=state)

    assert client.patch("/api/usage-sources/missing", json={"display_name": "x"}).status_code == 404
    assert client.post("/api/usage-sources/missing/token").status_code == 404
    assert client.post(
        "/api/usage-sources/missing/observations",
        headers={"X-Deskbar-Source-Token": "anything"},
        json=_obs(),
    ).status_code == 404

    source_id = client.post(
        "/api/usage-sources",
        json={"provider": "custom", "display_name": "Disable me"},
    ).get_json()["source"]["source_id"]
    token = client.post(f"/api/usage-sources/{source_id}/token").get_json()["token"]
    assert client.patch(f"/api/usage-sources/{source_id}", json={"enabled": False}).status_code == 200
    assert client.post(
        f"/api/usage-sources/{source_id}/observations",
        headers={"X-Deskbar-Source-Token": token},
        json=_obs(),
    ).status_code == 401

    assert client.patch(f"/api/usage-sources/{source_id}", json={"enabled": True, "archived": True}).status_code == 200
    assert client.post(f"/api/usage-sources/{source_id}/token").status_code == 400
    assert source_id not in {item["source_id"] for item in client.get("/api/usage-sources").get_json()["sources"]}

    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{ not json", encoding="utf-8")
    corrupt_state = AppState(corrupt_path)
    corrupt_client, _ = _client(tmp_path, monkeypatch, state=corrupt_state)
    before = corrupt_path.read_text(encoding="utf-8")
    assert corrupt_client.get("/api/usage-sources").status_code == 503
    assert corrupt_client.post(
        "/api/usage-sources",
        json={"provider": "claude", "display_name": "Claude"},
    ).status_code == 400
    assert corrupt_client.post("/api/usage", json=_null_legacy_payload()).status_code == 204
    assert corrupt_path.read_text(encoding="utf-8") == before
