import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tools import openai_usage


TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


class _Response:
    def __init__(self, status_code=200, headers=None, data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""
        self._data = data

    def iter_content(self, chunk_size=8192):
        yield b""

    def close(self):
        pass

    def json(self):
        if isinstance(self._data, BaseException):
            raise self._data
        return self._data


def _load_demo_module():
    path = TOOLS_DIR / "usage_push_demo.py"
    spec = importlib.util.spec_from_file_location("usage_push_demo_accounts", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _reset_openai_worker(demo):
    with demo._OA_FETCHING_LOCK:
        demo._OA_FETCHING = False
        demo._OA_LAST_REFRESH_MONO = None
    demo._SOURCE_REFRESH_EVENT.clear()


def _run_openai_refresh(demo):
    _reset_openai_worker(demo)
    thread = demo.refresh_openai_async(min_interval=0.0)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_openai_fetch_usage_keeps_account_from_credentials_used_for_request(monkeypatch):
    current = {"access": "token-a", "account_id": "acct-a"}
    calls = []

    def fake_load_credentials(*_args, **_kwargs):
        return current["access"], current["account_id"]

    class HTTP:
        def post(self, url, headers=None, **kwargs):
            calls.append({"url": url, "headers": dict(headers or {}), "kwargs": kwargs})
            current.update({"access": "token-b", "account_id": "acct-b"})
            return _Response(
                headers={
                    "x-codex-primary-used-percent": "17",
                    "x-codex-primary-reset-at": "1786932438",
                }
            )

    monkeypatch.setattr(openai_usage, "load_credentials", fake_load_credentials)

    result = openai_usage.fetch_usage(http=HTTP())

    assert result["used_pct"] == 17.0
    assert result["account_id"] == "acct-a"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-a"
    assert calls[0]["headers"]["chatgpt-account-id"] == "acct-a"
    assert "token-a" not in json.dumps(result)
    assert "token-b" not in json.dumps(result)


def test_openai_fetch_usage_omits_account_when_usage_is_not_valid(monkeypatch):
    class HTTP:
        def post(self, *_args, **_kwargs):
            return _Response(headers={"x-codex-primary-reset-at": "1786932438"})

    monkeypatch.setattr(openai_usage, "load_credentials", lambda *_a, **_k: ("token-a", "acct-a"))

    result = openai_usage.fetch_usage(http=HTTP())

    assert result["used_pct"] is None
    assert "account_id" not in result


def test_cache_replay_does_not_relabel_a_metrics_with_current_b_login(monkeypatch):
    demo = _load_demo_module()
    cached = {
        "session_pct": 9.0,
        "oa_weekly_pct": 31.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_fetched_at": "2026-08-25T03:01:00+00:00",
        "oa_account_id": "acct-a",
    }
    demo.warm_openai_from_cache(cached)

    def fail_if_used():
        raise AssertionError("compose must not read current OpenAI login")

    monkeypatch.setattr(demo, "fetch_openai_usage", fail_if_used)

    payload = demo.compose_publish_payload(
        cached,
        enable_claude=False,
        enable_antigravity=False,
        enable_openai=True,
    )

    assert payload["oa_weekly_pct"] == 31.0
    assert payload["oa_fetched_at"] == "2026-08-25T03:01:00+00:00"
    assert payload["oa_account_id"] == "acct-a"


def test_successful_b_observation_replaces_a_metrics_account_and_time(tmp_path, monkeypatch):
    demo = _load_demo_module()
    cache_path = tmp_path / "usage_cache.json"
    prior = {
        "oa_weekly_pct": 31.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_fetched_at": "2026-08-25T03:01:00+00:00",
        "oa_account_id": "acct-a",
    }
    demo.save_cache(prior, cache_path)
    demo.warm_openai_from_cache(prior)

    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, path=None: real_merge(fields, cache_path),
    )
    monkeypatch.setattr(
        demo,
        "fetch_openai_usage",
        lambda: {
            "used_pct": 62.0,
            "resets_at_epoch": 1786932438,
            "account_id": "acct-b",
        },
    )

    _run_openai_refresh(demo)

    mem = demo.get_openai_fields()
    cached = demo.load_cache(cache_path)
    assert mem["oa_weekly_pct"] == 62.0
    assert mem["oa_account_id"] == "acct-b"
    assert mem["oa_fetched_at"] != prior["oa_fetched_at"]
    assert cached["oa_weekly_pct"] == mem["oa_weekly_pct"]
    assert cached["oa_account_id"] == mem["oa_account_id"]
    assert cached["oa_fetched_at"] == mem["oa_fetched_at"]


def test_openai_failure_leaves_cached_a_observation_intact(tmp_path, monkeypatch):
    demo = _load_demo_module()
    cache_path = tmp_path / "usage_cache.json"
    prior = {
        "oa_weekly_pct": 31.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_fetched_at": "2026-08-25T03:01:00+00:00",
        "oa_account_id": "acct-a",
    }
    demo.save_cache(prior, cache_path)
    demo.warm_openai_from_cache(prior)

    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, path=None: real_merge(fields, cache_path),
    )
    monkeypatch.setattr(
        demo,
        "fetch_openai_usage",
        lambda: {"used_pct": None, "resets_at_epoch": None, "account_id": "acct-b"},
    )

    _run_openai_refresh(demo)

    assert demo.get_openai_fields() == prior
    assert demo.load_cache(cache_path) == prior


def test_openai_success_without_account_id_is_anonymous_and_drops_stale_id(
    tmp_path, monkeypatch
):
    demo = _load_demo_module()
    cache_path = tmp_path / "usage_cache.json"
    prior = {
        "oa_weekly_pct": 31.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_fetched_at": "2026-08-25T03:01:00+00:00",
        "oa_account_id": "acct-a",
    }
    demo.save_cache(prior, cache_path)
    demo.warm_openai_from_cache(prior)

    real_merge = demo.merge_source_fields_into_cache
    monkeypatch.setattr(
        demo,
        "merge_source_fields_into_cache",
        lambda fields, path=None: real_merge(fields, cache_path),
    )
    monkeypatch.setattr(
        demo,
        "fetch_openai_usage",
        lambda: {"used_pct": 14.0, "resets_at_epoch": 1786932438, "account_id": ""},
    )

    _run_openai_refresh(demo)

    mem = demo.get_openai_fields()
    cached = demo.load_cache(cache_path)
    assert mem["oa_weekly_pct"] == 14.0
    assert "oa_account_id" not in mem
    assert cached["oa_weekly_pct"] == 14.0
    assert "oa_account_id" not in cached


def test_named_enabled_account_source_enables_provider_despite_disabled_legacy(
    monkeypatch,
):
    demo = _load_demo_module()
    calls = []
    registry_url = "https://desk.example/api/usage-sources?include_archived=1"

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, dict(headers or {}), timeout))
        if url.endswith("/api/prefs"):
            return _Response(data={"usage_sources": []})
        if url == registry_url:
            return _Response(
                data={
                    "sources": [
                        {
                            "source_id": "disabled-a",
                            "provider": "openai",
                            "provider_account_id": "acct-a",
                            "enabled": False,
                            "archived": False,
                        },
                        {
                            "source_id": "legacy-openai-acct-b",
                            "provider": "openai",
                            "provider_account_id": "acct-b",
                            "enabled": True,
                            "archived": False,
                        },
                    ]
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(demo.requests, "get", fake_get)

    sources = demo.fetch_usage_sources("https://desk.example/api/prefs", "push-token")

    assert sources == ("openai",)
    assert [url for url, _headers, _timeout in calls] == [
        "https://desk.example/api/prefs",
        registry_url,
    ]
    assert calls[0][1] == {"X-Deskbar-Token": "push-token"}
    assert calls[1][1] == {"X-Deskbar-Token": "push-token"}


def test_enabled_anonymous_managed_source_enables_provider_without_account_id(monkeypatch):
    demo = _load_demo_module()
    registry_url = "https://desk.example/api/usage-sources?include_archived=1"

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/prefs"):
            return _Response(data={"usage_sources": []})
        if url == registry_url:
            return _Response(
                data={
                    "sources": [
                        {
                            "provider": "openai",
                            "provider_account_id": "acct-a",
                            "enabled": False,
                            "archived": False,
                        },
                        {
                            "provider": "openai",
                            "provider_account_id": "acct-b",
                            "enabled": True,
                            "archived": True,
                        },
                        {
                            "provider": "openai",
                            "provider_account_id": None,
                            "enabled": True,
                            "archived": False,
                        },
                    ]
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(demo.requests, "get", fake_get)

    assert demo.fetch_usage_sources("https://desk.example/api/prefs") == ("openai",)


def test_usage_sources_legacy_404_fallback_keeps_prefs_enabled_provider(monkeypatch):
    demo = _load_demo_module()
    registry_url = "https://desk.example/api/usage-sources?include_archived=1"

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/prefs"):
            return _Response(data={"usage_sources": ["openai"]})
        if url == registry_url:
            return _Response(status_code=404, data={"error": "not found"})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(demo.requests, "get", fake_get)

    assert demo.fetch_usage_sources("https://desk.example/api/prefs") == ("openai",)


def test_oa_payload_fields_empty_id_remains_legacy_anonymous():
    demo = _load_demo_module()
    now = demo.datetime(2026, 8, 10, 12, 0, 0, tzinfo=demo.timezone.utc)

    fields = demo.oa_payload_fields(
        {"used_pct": 9.0, "resets_at_epoch": None, "account_id": ""},
        now,
    )

    assert fields == {"oa_weekly_pct": 9.0, "oa_weekly_resets_at": None}
