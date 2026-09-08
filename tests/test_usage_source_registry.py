from __future__ import annotations

import json
import math
import stat
from datetime import datetime, timedelta, timezone

import pytest

import deskbar.usage_sources as usage_sources
from deskbar.usage_sources import UsageSourceStore


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _obs(
    *,
    account: str | None = None,
    pct: float = 42,
    observed_at: datetime | None = None,
    metric: str = "weekly",
    **metric_fields,
) -> dict:
    metric_payload = {"used_pct": pct, **metric_fields}
    return {
        "provider_account_id": account,
        "observed_at": _iso(observed_at or (_now() - timedelta(minutes=5))),
        "metrics": {metric: metric_payload},
    }


def _source(store: UsageSourceStore, source_id: str) -> dict:
    return next(
        source
        for source in store.list_sources(include_archived=True)
        if source["source_id"] == source_id
    )


def test_same_provider_accounts_are_isolated_and_rename_does_not_rekey():
    store = UsageSourceStore()

    work = store.create_source(
        {"provider": "codex", "provider_account_id": "acct-work", "display_name": "Work"}
    )
    personal = store.create_source(
        {
            "provider": "openai",
            "provider_account_id": "acct-personal",
            "display_name": "Personal",
        }
    )

    assert work["provider"] == "openai"
    assert work["source_id"] != personal["source_id"]
    with pytest.raises(ValueError):
        store.create_source({"provider": "codex", "provider_account_id": "acct-work"})

    store.observe(work["source_id"], _obs(account="acct-work", pct=18))
    store.observe(personal["source_id"], _obs(account="acct-personal", pct=73))
    renamed = store.update_source(work["source_id"], {"display_name": "Renamed Work"})

    assert renamed["source_id"] == work["source_id"]
    assert renamed["provider_account_id"] == "acct-work"
    assert _source(store, work["source_id"])["observation"]["metrics"]["weekly"]["used_pct"] == 18
    assert _source(store, personal["source_id"])["observation"]["metrics"]["weekly"]["used_pct"] == 73
    with pytest.raises(ValueError):
        store.update_source(work["source_id"], {"provider_account_id": "acct-other"})


def test_sources_persist_with_mode600_and_reload_without_exposing_token_hash(tmp_path):
    path = tmp_path / "sources.json"
    store = UsageSourceStore(path)
    source = store.create_source(
        {
            "provider": "custom",
            "display_name": "Build quota",
            "selected_metrics": ["weekly"],
            "stale_after_hours": 48,
            "hide_when_stale": False,
        }
    )
    window_end = _now() - timedelta(minutes=2)
    store.observe(
        source["source_id"],
        _obs(
            pct=44,
            observed_at=window_end,
            resets_at=_iso(window_end + timedelta(days=1)),
            window_start=_iso(window_end - timedelta(days=7)),
            window_end=_iso(window_end),
        ),
    )
    token_result = store.rotate_token(source["source_id"])

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert token_result["token"] not in path.read_text(encoding="utf-8")

    reloaded = UsageSourceStore(path)
    listed = _source(reloaded, source["source_id"])
    serialized = json.dumps(listed, sort_keys=True)

    assert listed["display_name"] == "Build quota"
    assert listed["status"] == "ok"
    assert listed["token_set"] is True
    assert listed["observation"]["metrics"]["weekly"]["used_pct"] == 44
    assert token_result["token"] not in serialized
    assert "sha256" not in serialized.lower()


def test_persistence_failure_leaves_memory_and_disk_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "sources.json"
    store = UsageSourceStore(path)
    source = store.create_source({"provider": "claude", "display_name": "Claude"})
    before_memory = json.dumps(_source(store, source["source_id"]), sort_keys=True)
    before_disk = path.read_text(encoding="utf-8")

    def fail_replace(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(usage_sources.os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.update_source(source["source_id"], {"display_name": "Should not commit"})

    assert json.dumps(_source(store, source["source_id"]), sort_keys=True) == before_memory
    assert path.read_text(encoding="utf-8") == before_disk


def test_concurrent_update_uses_latest_disk_state(tmp_path):
    path = tmp_path / "sources.json"
    first = UsageSourceStore(path)
    source = first.create_source({"provider": "claude", "display_name": "Claude"})
    second = UsageSourceStore(path)

    first.update_source(source["source_id"], {"display_name": "Claude Team"})
    second.update_source(source["source_id"], {"visible": False})

    final = UsageSourceStore(path)
    listed = _source(final, source["source_id"])
    assert listed["display_name"] == "Claude Team"
    assert listed["visible"] is False


def test_stale_cache_replay_and_older_observations_do_not_refresh_observed_or_received_at():
    store = UsageSourceStore()
    source = store.create_source(
        {"provider": "openai", "provider_account_id": "acct", "stale_after_hours": 1}
    )
    stale_time = _now() - timedelta(hours=2)
    first = store.observe(source["source_id"], _obs(account="acct", pct=25, observed_at=stale_time))

    assert first["accepted"] is True
    assert _source(store, source["source_id"])["status"] == "stale"
    before = json.dumps(_source(store, source["source_id"])["observation"], sort_keys=True)

    equal = store.observe(source["source_id"], _obs(account="acct", pct=99, observed_at=stale_time))
    older = store.observe(
        source["source_id"],
        _obs(account="acct", pct=88, observed_at=stale_time - timedelta(seconds=1)),
    )

    assert equal["accepted"] is False
    assert older["accepted"] is False
    assert json.dumps(_source(store, source["source_id"])["observation"], sort_keys=True) == before

    fresh_time = _now() - timedelta(minutes=2)
    fresh = store.observe(source["source_id"], _obs(account="acct", pct=31, observed_at=fresh_time))
    assert fresh["accepted"] is True
    assert _source(store, source["source_id"])["status"] == "ok"


def test_legacy_payload_maps_flat_sources_and_provider_toggles_only_legacy_bindings():
    store = UsageSourceStore()
    manual = store.create_source(
        {
            "provider": "claude",
            "provider_account_id": "team@example.com",
            "display_name": "Team Claude",
        }
    )
    observed_at = _now() - timedelta(minutes=3)

    result = store.ingest_legacy(
        {
            "fetched_at": _iso(observed_at),
            "claude": {"session": 10, "weekly": 20, "fable": None},
            "antigravity": {"5h": {"used_pct": 30}, "weekly": 40},
            "openai_weekly": 50,
        },
        enabled_providers=["claude", "antigravity", "openai"],
    )

    assert set(result["accepted_source_ids"]) == {
        "legacy-claude",
        "legacy-antigravity",
        "legacy-openai",
    }
    assert set(_source(store, "legacy-claude")["observation"]["metrics"]) == {"session", "weekly"}
    assert _source(store, "legacy-antigravity")["observation"]["metrics"]["5h"]["used_pct"] == 30
    assert _source(store, "legacy-openai")["observation"]["metrics"]["weekly"]["used_pct"] == 50

    store.ingest_legacy(
        {"fetched_at": _iso(_now() - timedelta(minutes=1)), "claude": {"weekly": 22}},
        enabled_providers=[],
    )
    assert _source(store, "legacy-claude")["enabled"] is False
    assert _source(store, manual["source_id"])["enabled"] is True


def test_identified_legacy_openai_creates_account_source_without_erasing_anonymous_data():
    store = UsageSourceStore()
    first_seen = _now() - timedelta(minutes=10)
    store.ingest_legacy(
        {"fetched_at": _iso(first_seen), "openai": {"weekly": 33}},
        enabled_providers=["openai"],
    )
    store.update_source("legacy-openai", {"display_name": "Legacy Codex"})

    identified_seen = _now() - timedelta(minutes=5)
    result = store.ingest_legacy(
        {
            "fetched_at": _iso(identified_seen),
            "oa_account_id": "acct-openai-work",
            "openai": {"weekly": 55},
        },
        enabled_providers=["openai"],
    )
    account_id = result["accepted_source_ids"][0]
    account_source = _source(store, account_id)

    assert account_source["provider"] == "openai"
    assert account_source["provider_account_id"] == "acct-openai-work"
    assert account_source["observation"]["metrics"]["weekly"]["used_pct"] == 55
    assert _source(store, "legacy-openai")["display_name"] == "Legacy Codex"
    assert _source(store, "legacy-openai")["observation"]["metrics"]["weekly"]["used_pct"] == 33

    store.update_source(account_id, {"display_name": "Work Codex", "selected_metrics": ["weekly"]})
    store.ingest_legacy(
        {
            "fetched_at": _iso(_now() - timedelta(minutes=1)),
            "oa_account_id": "acct-openai-work",
            "openai": {"weekly": 56},
        },
        enabled_providers=["openai"],
    )
    assert _source(store, account_id)["display_name"] == "Work Codex"
    assert _source(store, account_id)["selected_metrics"] == ["weekly"]


def test_disabled_and_archived_sources_reject_updates_and_legacy_tombstones_do_not_resurrect():
    store = UsageSourceStore()
    disabled = store.create_source(
        {"provider": "openai", "provider_account_id": "acct-disabled", "enabled": False}
    )

    with pytest.raises(ValueError):
        store.observe(disabled["source_id"], _obs(account="acct-disabled", pct=20))

    store.ingest_legacy(
        {
            "fetched_at": _iso(_now() - timedelta(minutes=5)),
            "oa_account_id": "acct-disabled",
            "openai": {"weekly": 64},
        },
        enabled_providers=["openai"],
    )
    assert _source(store, disabled["source_id"])["observation"] is None

    store.ingest_legacy(
        {"fetched_at": _iso(_now() - timedelta(minutes=5)), "claude": {"weekly": 11}},
        enabled_providers=["claude"],
    )
    store.update_source("legacy-claude", {"archived": True})
    before = json.dumps(_source(store, "legacy-claude"), sort_keys=True)
    store.ingest_legacy(
        {"fetched_at": _iso(_now() - timedelta(minutes=1)), "claude": {"weekly": 91}},
        enabled_providers=["claude"],
    )

    assert "legacy-claude" not in {source["source_id"] for source in store.list_sources()}
    assert json.dumps(_source(store, "legacy-claude"), sort_keys=True) == before


def test_invalid_numbers_windows_and_timestamps_are_atomic_noops():
    store = UsageSourceStore()
    source = store.create_source({"provider": "custom", "display_name": "Custom"})
    store.observe(source["source_id"], _obs(pct=10))
    before = json.dumps(_source(store, source["source_id"]), sort_keys=True)
    window_end = _now() - timedelta(minutes=1)

    invalid_payloads = [
        _obs(pct=None),
        _obs(pct=True),
        _obs(pct=math.nan),
        _obs(pct=101),
        {"provider_account_id": None, "observed_at": _iso(window_end), "metrics": {}},
        _obs(metric="bad metric", pct=10),
        _obs(observed_at=(_now() + timedelta(minutes=3))),
        _obs(observed_at=datetime.now()),
        _obs(
            pct=10,
            window_start=_iso(window_end),
            window_end=_iso(window_end - timedelta(seconds=1)),
        ),
        _obs(
            pct=10,
            window_start=_iso(window_end - timedelta(days=367, seconds=1)),
            window_end=_iso(window_end),
        ),
    ]

    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            store.observe(source["source_id"], payload)
        assert json.dumps(_source(store, source["source_id"]), sort_keys=True) == before


def test_token_rotation_verification_and_redaction_are_source_scoped():
    store = UsageSourceStore()
    first = store.create_source({"provider": "custom", "display_name": "First"})
    second = store.create_source({"provider": "custom", "display_name": "Second"})

    first_token = store.rotate_token(first["source_id"])["token"]
    second_token = store.rotate_token(second["source_id"])["token"]

    assert store.verify_token(first["source_id"], first_token) is True
    assert store.verify_token(second["source_id"], first_token) is False
    assert store.verify_token(first["source_id"], second_token) is False
    assert store.verify_token(first["source_id"], "") is False

    replacement = store.rotate_token(first["source_id"])["token"]
    assert store.verify_token(first["source_id"], first_token) is False
    assert store.verify_token(first["source_id"], replacement) is True

    with pytest.raises(KeyError) as exc:
        store.verify_token("missing", "secret-token-value")
    assert "secret-token-value" not in str(exc.value)

    serialized = json.dumps(store.list_sources(include_archived=True), sort_keys=True)
    assert first_token not in serialized
    assert second_token not in serialized
    assert replacement not in serialized
    assert "sha256" not in serialized.lower()


def test_strict_source_validation_rejects_unknown_immutable_and_out_of_bounds_fields():
    store = UsageSourceStore()
    source = store.create_source({"provider": "claude", "display_name": "Claude"})

    create_failures = [
        {"provider": "claude", "display_name": ""},
        {"provider": "claude", "display_name": "x" * 81},
        {"provider": "openai", "provider_account_id": "x" * 161},
        {"provider": "custom", "visible": 1},
        {"provider": "custom", "unknown": True},
        {"provider": "unknown"},
    ]
    for payload in create_failures:
        with pytest.raises(ValueError):
            store.create_source(payload)

    update_failures = [
        {"provider": "openai"},
        {"source_id": "other"},
        {"provider_account_id": "other"},
        {"visible": 1},
        {"enabled": 0},
        {"hide_when_stale": 1},
        {"selected_metrics": ["bad space"]},
        {"selected_metrics": [f"m{i}" for i in range(13)]},
        {"stale_after_hours": 0},
        {"stale_after_hours": 721},
        {"order": True},
        {"unexpected": True},
    ]
    for payload in update_failures:
        with pytest.raises(ValueError):
            store.update_source(source["source_id"], payload)

    full = UsageSourceStore()
    for i in range(64):
        full.create_source({"provider": "custom", "display_name": f"Source {i}"})
    with pytest.raises(ValueError):
        full.create_source({"provider": "custom", "display_name": "Too many"})


def test_corrupt_persistence_reports_error_and_refuses_to_overwrite_file(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text("{ not json", encoding="utf-8")
    path.chmod(0o600)

    store = UsageSourceStore(path)
    assert store.load_error
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        store.create_source({"provider": "claude", "display_name": "Claude"})

    assert path.read_text(encoding="utf-8") == before
