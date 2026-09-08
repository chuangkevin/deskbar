from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import deskbar.usage_sources as usage_sources
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.usage_sources import UsageSourceStore
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


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _legacy_usage_payload(
    *,
    minutes_ago: int,
    claude_pct: float | None,
    ag_pct: float | None,
) -> dict:
    return {
        "fetched_at": _iso(minutes_ago),
        "weekly_pct": claude_pct,
        "ag_weekly_pct": ag_pct,
    }


def _observation(*, pct: float, minutes_ago: int = 5) -> dict:
    return {
        "provider_account_id": None,
        "observed_at": _iso(minutes_ago),
        "metrics": {"weekly": {"used_pct": pct}},
    }


def _source(state: AppState, source_id: str) -> dict:
    return next(
        item
        for item in state.list_usage_sources(include_archived=True)
        if item["source_id"] == source_id
    )


def test_legacy_usage_push_preserves_explicit_source_pause_and_keeps_other_sources_updating(
    tmp_path,
    monkeypatch,
):
    settings = Settings()
    client, state = _client(tmp_path, monkeypatch, settings=settings)

    assert client.post(
        "/api/usage",
        json=_legacy_usage_payload(minutes_ago=10, claude_pct=21, ag_pct=31),
    ).status_code == 204
    pause = client.patch("/api/usage-sources/legacy-claude", json={"enabled": False})
    assert pause.status_code == 200
    before_claude_observation = json.dumps(
        _source(state, "legacy-claude")["observation"],
        sort_keys=True,
    )

    assert client.post(
        "/api/usage",
        json=_legacy_usage_payload(minutes_ago=4, claude_pct=88, ag_pct=47),
    ).status_code == 204

    claude = _source(state, "legacy-claude")
    antigravity = _source(state, "legacy-antigravity")
    assert claude["enabled"] is False
    assert json.dumps(claude["observation"], sort_keys=True) == before_claude_observation
    assert antigravity["enabled"] is True
    assert antigravity["observation"]["metrics"]["weekly"]["used_pct"] == 47

    r = client.patch(
        "/api/prefs",
        json={"usage_sources": ["claude", "antigravity", "openai"]},
    )
    assert r.status_code == 200
    claude = _source(state, "legacy-claude")
    assert claude["enabled"] is False
    assert json.dumps(claude["observation"], sort_keys=True) == before_claude_observation
    assert _source(state, "legacy-antigravity")["enabled"] is True
    assert _source(state, "legacy-antigravity")["observation"]["metrics"]["weekly"]["used_pct"] == 47

    r = client.patch(
        "/api/prefs",
        json={"usage_sources": ["antigravity", "openai"]},
    )
    assert r.status_code == 200
    assert _source(state, "legacy-claude")["enabled"] is False

    r = client.patch(
        "/api/prefs",
        json={"usage_sources": ["claude", "antigravity", "openai"]},
    )
    assert r.status_code == 200
    claude = _source(state, "legacy-claude")
    assert claude["enabled"] is True
    assert json.dumps(claude["observation"], sort_keys=True) == before_claude_observation
    assert _source(state, "legacy-antigravity")["enabled"] is True
    assert _source(state, "legacy-antigravity")["observation"]["metrics"]["weekly"]["used_pct"] == 47


def test_first_anonymous_legacy_source_creation_honors_current_prefs(tmp_path, monkeypatch):
    settings = Settings(usage_sources=("antigravity",))
    client, state = _client(tmp_path, monkeypatch, settings=settings)

    assert client.post(
        "/api/usage",
        json=_legacy_usage_payload(minutes_ago=5, claude_pct=21, ag_pct=31),
    ).status_code == 204

    source_ids = {
        item["source_id"]
        for item in state.list_usage_sources(include_archived=True)
    }
    assert "legacy-claude" not in source_ids
    assert _source(state, "legacy-antigravity")["enabled"] is True


def test_prefs_usage_sources_sync_failure_returns_503_without_saving_or_mutating(
    tmp_path,
    monkeypatch,
):
    settings = Settings()
    state = AppState(tmp_path / "usage_sources.json")
    client, _ = _client(tmp_path, monkeypatch, state=state, settings=settings)
    assert client.post(
        "/api/usage",
        json=_legacy_usage_payload(minutes_ago=5, claude_pct=21, ag_pct=None),
    ).status_code == 204
    before_disk = (tmp_path / "usage_sources.json").read_text(encoding="utf-8")
    before_source = json.dumps(_source(state, "legacy-claude"), sort_keys=True)

    def fail_registry_replace(_src, dst):
        if str(dst).endswith("usage_sources.json"):
            raise OSError("disk full at /tmp/secret-path")
        return real_replace(_src, dst)

    real_replace = usage_sources.os.replace
    monkeypatch.setattr(usage_sources.os, "replace", fail_registry_replace)

    r = client.patch("/api/prefs", json={"usage_sources": ["openai"]})

    assert r.status_code == 503
    assert r.get_json() == {"error": "usage sources update failed"}
    assert settings.usage_sources == ("claude", "antigravity", "openai")
    assert client._saved == []
    assert (tmp_path / "usage_sources.json").read_text(encoding="utf-8") == before_disk
    assert json.dumps(_source(state, "legacy-claude"), sort_keys=True) == before_source


def test_corrupt_registry_get_returns_503_without_local_details(tmp_path, monkeypatch):
    path = tmp_path / "usage_sources.json"
    path.write_text("{ not json", encoding="utf-8")
    client, _state = _client(tmp_path, monkeypatch, state=AppState(path))

    r = client.get("/api/usage-sources")

    assert r.status_code == 503
    body = json.dumps(r.get_json(), sort_keys=True)
    assert "usage sources unavailable" in body
    assert str(path) not in body
    assert "secret" not in body.lower()


def test_invalid_scoped_source_id_returns_400_before_token_lookup(tmp_path, monkeypatch):
    client, _state = _client(tmp_path, monkeypatch)
    invalid_id = "x" * 161

    r = client.post(
        f"/api/usage-sources/{invalid_id}/observations",
        headers={"X-Deskbar-Source-Token": "anything"},
        json=_observation(pct=10),
    )

    assert r.status_code == 400
    assert r.get_json() == {"error": "invalid source_id"}


def test_memory_only_registry_serializes_concurrent_mutations_without_losing_newer_observation():
    store = UsageSourceStore()
    source = store.create_source({"provider": "custom", "display_name": "Concurrent"})
    ready = threading.Barrier(3)
    release = threading.Event()
    results = []

    def observe(pct: float, minutes_ago: int):
        ready.wait(timeout=1)
        release.wait(timeout=1)
        results.append(
            store.observe(
                source["source_id"],
                _observation(pct=pct, minutes_ago=minutes_ago),
            )
        )

    older = threading.Thread(target=observe, args=(11, 8))
    newer = threading.Thread(target=observe, args=(91, 2))
    older.start()
    newer.start()
    ready.wait(timeout=1)
    with store._lock:
        release.set()
        time.sleep(0.05)
        assert results == []
    older.join(timeout=1)
    newer.join(timeout=1)

    assert not older.is_alive()
    assert not newer.is_alive()
    assert len(results) == 2
    final = next(
        item
        for item in store.list_sources(include_archived=True)
        if item["source_id"] == source["source_id"]
    )
    assert final["observation"]["metrics"]["weekly"]["used_pct"] == 91
