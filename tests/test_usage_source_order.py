from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import deskbar.usage_sources as usage_sources
from deskbar.store import AppState
from deskbar.usage_sources import UsageSourceStore
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


def _client(tmp_path, monkeypatch, *, state=None):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DESKBAR_PUSH_TOKEN", raising=False)
    state = state or AppState(tmp_path / "usage_sources.json")
    app = create_app(_FakeStore(), usage_state=state)
    app.config["TESTING"] = True
    return app.test_client(), state


def _create_sources(store_or_state, names: list[str]) -> list[dict]:
    return [
        store_or_state.create_usage_source({"provider": "custom", "display_name": name})
        if isinstance(store_or_state, AppState)
        else store_or_state.create_source({"provider": "custom", "display_name": name})
        for name in names
    ]


def _store_active_ids(store: UsageSourceStore) -> list[str]:
    return [source["source_id"] for source in store.list_sources()]


def _state_active_ids(state: AppState) -> list[str]:
    return [source["source_id"] for source in state.list_usage_sources()]


def _all_sources_json(store_or_state) -> str:
    if isinstance(store_or_state, AppState):
        sources = store_or_state.list_usage_sources(include_archived=True)
    else:
        sources = store_or_state.list_sources(include_archived=True)
    return json.dumps(sources, sort_keys=True)


def _source_by_id(store: UsageSourceStore, source_id: str) -> dict:
    return next(
        source
        for source in store.list_sources(include_archived=True)
        if source["source_id"] == source_id
    )


def _obs() -> dict:
    return {
        "provider_account_id": None,
        "observed_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "metrics": {"weekly": {"used_pct": 42}},
    }


def test_store_reorder_reverses_active_sources_and_only_changes_order():
    store = UsageSourceStore()
    first, second, third = _create_sources(store, ["A", "B", "C"])
    store.update_source(second["source_id"], {"selected_metrics": ["weekly"]})
    before_second = _source_by_id(store, second["source_id"])

    result = store.reorder_sources(
        [third["source_id"], second["source_id"], first["source_id"]]
    )

    assert [source["source_id"] for source in result] == [
        third["source_id"],
        second["source_id"],
        first["source_id"],
    ]
    assert [source["order"] for source in result] == [0, 1, 2]
    after_second = _source_by_id(store, second["source_id"])
    assert after_second == {**before_second, "order": 1}


def test_invalid_reorder_sets_are_rejected_without_mutation():
    store = UsageSourceStore()
    first, second, _third = _create_sources(store, ["A", "B", "C"])
    before = _all_sources_json(store)

    invalid_payloads = [
        "not-a-list",
        [first["source_id"], first["source_id"], second["source_id"]],
        [first["source_id"], second["source_id"]],
        [first["source_id"], second["source_id"], "missing"],
        [first["source_id"], second["source_id"], 3],
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            store.reorder_sources(payload)
        assert _all_sources_json(store) == before


def test_reorder_preserves_archived_sources_and_observations():
    store = UsageSourceStore()
    first, archived, third = _create_sources(store, ["A", "Archived", "C"])
    store.observe(archived["source_id"], _obs())
    store.update_source(archived["source_id"], {"archived": True})
    before_archived = _source_by_id(store, archived["source_id"])

    result = store.reorder_sources([third["source_id"], first["source_id"]])

    assert [source["source_id"] for source in result] == [third["source_id"], first["source_id"]]
    assert _source_by_id(store, archived["source_id"]) == before_archived
    assert archived["source_id"] not in _store_active_ids(store)


def test_reorder_persists_and_survives_restart(tmp_path):
    path = tmp_path / "usage_sources.json"
    store = UsageSourceStore(path)
    first, second, third = _create_sources(store, ["A", "B", "C"])

    store.reorder_sources([third["source_id"], first["source_id"], second["source_id"]])

    reloaded = UsageSourceStore(path)
    assert _store_active_ids(reloaded) == [
        third["source_id"],
        first["source_id"],
        second["source_id"],
    ]
    assert [source["order"] for source in reloaded.list_sources()] == [0, 1, 2]


def test_reorder_disk_failure_returns_503_and_leaves_memory_and_disk_unchanged(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "usage_sources.json"
    state = AppState(path)
    first, second = _create_sources(state, ["A", "B"])
    client, _ = _client(tmp_path, monkeypatch, state=state)
    before_memory = _all_sources_json(state)
    before_snapshot = list(state.snapshot().usage_sources)
    before_disk = path.read_text(encoding="utf-8")

    def fail_replace(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(usage_sources.os, "replace", fail_replace)
    response = client.post(
        "/api/usage-sources/order",
        json={"source_ids": [second["source_id"], first["source_id"]]},
    )

    assert response.status_code == 503
    assert _all_sources_json(state) == before_memory
    assert state.snapshot().usage_sources == before_snapshot
    assert path.read_text(encoding="utf-8") == before_disk


def test_api_reorder_rejects_invalid_sets_with_400_and_keeps_prior_order(tmp_path, monkeypatch):
    state = AppState(tmp_path / "usage_sources.json")
    first, second, third = _create_sources(state, ["A", "B", "C"])
    client, _ = _client(tmp_path, monkeypatch, state=state)
    before = _all_sources_json(state)

    invalid_payloads = [
        {"source_ids": [first["source_id"], first["source_id"], second["source_id"]]},
        {"source_ids": [first["source_id"], second["source_id"]]},
        {"source_ids": [first["source_id"], second["source_id"], "missing"]},
        {"source_ids": "not-a-list"},
    ]
    for payload in invalid_payloads:
        response = client.post("/api/usage-sources/order", json=payload)
        assert response.status_code == 400
        assert _all_sources_json(state) == before

    assert _state_active_ids(state) == [
        first["source_id"],
        second["source_id"],
        third["source_id"],
    ]


def test_api_reorder_auth_failure_noops_and_same_request_can_retry_with_token(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DESKBAR_PUSH_TOKEN", "push-secret")
    state = AppState(tmp_path / "usage_sources.json")
    first, second = _create_sources(state, ["A", "B"])
    app = create_app(_FakeStore(), usage_state=state)
    app.config["TESTING"] = True
    client = app.test_client()
    body = {"source_ids": [second["source_id"], first["source_id"]]}
    before = _all_sources_json(state)

    unauthorized = client.post("/api/usage-sources/order", json=body)

    assert unauthorized.status_code == 401
    assert _all_sources_json(state) == before

    cross_site = client.post(
        "/api/usage-sources/order",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "https://evil.example", "X-Deskbar-Token": "push-secret"},
        json=body,
    )
    assert cross_site.status_code == 403
    assert _all_sources_json(state) == before

    retry = client.post(
        "/api/usage-sources/order",
        headers={"X-Deskbar-Token": "push-secret"},
        json=body,
    )

    assert retry.status_code == 200
    assert [source["source_id"] for source in retry.get_json()["sources"]] == body["source_ids"]
    assert _state_active_ids(state) == body["source_ids"]
    assert [source["source_id"] for source in state.snapshot().usage_sources] == body["source_ids"]


def test_web_move_usage_source_uses_atomic_order_endpoint():
    html = (Path(__file__).parent.parent / "deskbar" / "web" / "index.html").read_text(
        encoding="utf-8"
    )
    start = html.index("async function moveUsageSource")
    end = html.index("async function savePrefs")
    block = html[start:end]

    assert 'usageRequest("POST","/api/usage-sources/order"' in block
    assert "source_ids:sourceIds" in block
    assert "orderPending" in block
    assert "usagePatch(current.source_id" not in block
    assert "usagePatch(other.source_id" not in block
