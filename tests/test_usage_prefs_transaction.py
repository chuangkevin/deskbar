from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta, timezone

import deskbar.usage_sources as usage_sources
from deskbar.config import AccountCfg, Settings
from deskbar.store import AppState
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


class _ObservableLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._meta_lock = threading.Lock()
        self._attempts = 0
        self.second_attempted = threading.Event()

    def __enter__(self):
        with self._meta_lock:
            self._attempts += 1
            if self._attempts == 2:
                self.second_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self._lock.release()


def _app(tmp_path, monkeypatch, *, state=None, settings=None, settings_lock=None, on_save=None):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DESKBAR_PUSH_TOKEN", raising=False)
    state = state or AppState(tmp_path / "usage_sources.json")
    settings = settings or Settings()
    saves = []

    def save(settings_provider):
        saves.append(tuple(settings_provider.usage_sources))
        if on_save is not None:
            on_save(settings_provider)

    app = create_app(
        _FakeStore(),
        settings_provider=settings,
        settings_lock=settings_lock or threading.Lock(),
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


def _legacy_flags(state: AppState) -> dict[str, tuple[bool, bool]]:
    return {
        source_id: (
            _source(state, source_id)["enabled"],
            _source(state, source_id)["visible"],
        )
        for source_id in ("legacy-claude", "legacy-antigravity", "legacy-openai")
    }


def _make_legacy_sources(app, state):
    assert _client(app).post("/api/usage", json=_legacy_payload()).status_code == 204
    assert {source["source_id"] for source in state.list_usage_sources(include_archived=True)} >= {
        "legacy-claude",
        "legacy-antigravity",
        "legacy-openai",
    }


def test_usage_sources_save_failure_restores_prefs_and_exact_legacy_flags(
    tmp_path,
    monkeypatch,
):
    def fail_save(_settings):
        raise OSError("settings write failed in tmp callback")

    app, state, settings, saves = _app(tmp_path, monkeypatch, on_save=fail_save)
    _make_legacy_sources(app, state)
    state.update_usage_source("legacy-claude", {"enabled": False, "visible": False})
    named = state.create_usage_source(
        {
            "provider": "claude",
            "provider_account_id": "team@example.com",
            "display_name": "Team Claude",
        }
    )
    settings.accounts["control@example.com"] = AccountCfg("control", 3, {"primary": True})
    before_settings = copy.deepcopy(settings.__dict__)
    before_flags = _legacy_flags(state)
    before_named = json.dumps(_source(state, named["source_id"]), sort_keys=True)

    response = _client(app).patch("/api/prefs", json={"usage_sources": ["claude", "openai"]})

    assert response.status_code == 503
    assert response.get_json() == {"error": "usage sources update failed"}
    assert settings.__dict__ == before_settings
    assert saves == [("claude", "openai")]
    assert _legacy_flags(state) == before_flags
    assert json.dumps(_source(state, named["source_id"]), sort_keys=True) == before_named


def test_same_usage_sources_save_does_not_reenable_manually_hidden_legacy_source(
    tmp_path,
    monkeypatch,
):
    app, state, settings, _saves = _app(tmp_path, monkeypatch)
    _make_legacy_sources(app, state)
    state.update_usage_source("legacy-claude", {"enabled": False, "visible": False})

    response = _client(app).patch(
        "/api/prefs",
        json={"usage_sources": list(settings.usage_sources), "sync_interval_min": 10},
    )

    assert response.status_code == 200
    assert settings.sync_interval_min == 10
    claude = _source(state, "legacy-claude")
    assert claude["enabled"] is False
    assert claude["visible"] is False


def test_unrelated_provider_toggle_does_not_reset_manual_claude_flags(
    tmp_path,
    monkeypatch,
):
    app, state, _settings, _saves = _app(tmp_path, monkeypatch)
    _make_legacy_sources(app, state)
    state.update_usage_source("legacy-claude", {"enabled": False, "visible": False})

    response = _client(app).patch("/api/prefs", json={"usage_sources": ["claude", "openai"]})

    assert response.status_code == 200
    claude = _source(state, "legacy-claude")
    antigravity = _source(state, "legacy-antigravity")
    assert claude["enabled"] is False
    assert claude["visible"] is False
    assert antigravity["enabled"] is False
    assert antigravity["visible"] is False


def test_concurrent_usage_source_prefs_updates_serialize_registry_sync_and_save(
    tmp_path,
    monkeypatch,
):
    settings_lock = _ObservableLock()
    events = []
    events_lock = threading.Lock()
    first_save_entered = threading.Event()
    release_first_save = threading.Event()
    save_count = 0

    real_sync = usage_sources._sync_legacy_enabled_in_place

    def spy_sync(staged, enabled, now, *, sync_visible=False, providers=None):
        with events_lock:
            events.append(
                (
                    "sync",
                    tuple(sorted(enabled)),
                    None if providers is None else tuple(sorted(providers)),
                )
            )
        kwargs = {"sync_visible": sync_visible}
        if providers is not None:
            kwargs["providers"] = providers
        return real_sync(staged, enabled, now, **kwargs)

    def save(settings_provider):
        nonlocal save_count
        with events_lock:
            save_count += 1
            current_count = save_count
            events.append(("save-enter", tuple(settings_provider.usage_sources)))
        if current_count == 1:
            first_save_entered.set()
            assert release_first_save.wait(timeout=2)
        with events_lock:
            events.append(("save-exit", tuple(settings_provider.usage_sources)))

    monkeypatch.setattr(usage_sources, "_sync_legacy_enabled_in_place", spy_sync)
    app, state, settings, _saves = _app(
        tmp_path,
        monkeypatch,
        settings_lock=settings_lock,
        on_save=save,
    )
    _make_legacy_sources(app, state)
    results = {}

    def patch(name: str, sources: list[str]):
        with app.test_client() as client:
            results[name] = client.patch("/api/prefs", json={"usage_sources": sources}).status_code

    first = threading.Thread(target=patch, args=("first", ["openai"]))
    first.start()
    assert first_save_entered.wait(timeout=1)
    second = threading.Thread(target=patch, args=("second", ["claude", "openai"]))
    second.start()
    assert settings_lock.second_attempted.wait(timeout=1)

    with events_lock:
        before_release = list(events)
    first_save_index = before_release.index(("save-enter", ("openai",)))
    assert all(event[0] != "sync" for event in before_release[first_save_index + 1 :])

    release_first_save.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results == {"first": 200, "second": 200}
    assert settings.usage_sources == ("claude", "openai")
    assert _legacy_flags(state) == {
        "legacy-claude": (True, True),
        "legacy-antigravity": (False, False),
        "legacy-openai": (True, True),
    }
    with events_lock:
        sync_events = [event for event in events if event[0] == "sync"]
    assert sync_events == [
        ("sync", ("openai",), ("antigravity", "claude")),
        ("sync", ("claude", "openai"), ("claude",)),
    ]


def test_usage_sources_save_failure_reports_recovery_required_when_rollback_fails(
    tmp_path,
    monkeypatch,
):
    def fail_save(_settings):
        raise OSError("settings write failed in tmp callback")

    app, state, settings, _saves = _app(tmp_path, monkeypatch, on_save=fail_save)
    _make_legacy_sources(app, state)
    before_settings = copy.deepcopy(settings.__dict__)
    real_replace = usage_sources.os.replace
    usage_source_replaces = 0

    def fail_rollback_replace(src, dst):
        nonlocal usage_source_replaces
        if str(dst).endswith("usage_sources.json"):
            usage_source_replaces += 1
            if usage_source_replaces == 2:
                raise OSError("rollback failed in tmp callback")
        return real_replace(src, dst)

    monkeypatch.setattr(usage_sources.os, "replace", fail_rollback_replace)

    response = _client(app).patch("/api/prefs", json={"usage_sources": ["openai"]})

    assert response.status_code == 503
    assert response.get_json() == {"error": "usage sources recovery required"}
    assert settings.__dict__ == before_settings
    assert state.usage_source_store.load_error is not None
