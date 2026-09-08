import importlib.util
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


class _Response:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self.text = ""
        self._data = data

    def json(self):
        if isinstance(self._data, BaseException):
            raise self._data
        return self._data


def _load_demo_module():
    path = TOOLS_DIR / "usage_push_demo.py"
    spec = importlib.util.spec_from_file_location("usage_push_demo_pause", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fetch_sources(monkeypatch, *, legacy_sources, registry_sources, status_code=200):
    demo = _load_demo_module()
    calls = []
    prefs_url = "https://desk.example/collector/api/prefs"
    registry_url = (
        "https://desk.example/collector/api/usage-sources?include_archived=1"
    )

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, dict(headers or {}), timeout))
        if url == prefs_url:
            return _Response(data={"usage_sources": legacy_sources})
        if url == registry_url:
            return _Response(
                status_code=status_code,
                data={"sources": registry_sources},
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(demo.requests, "get", fake_get)

    result = demo.fetch_usage_sources(prefs_url, "push-token")

    assert calls == [
        (prefs_url, {"X-Deskbar-Token": "push-token"}, 5),
        (registry_url, {"X-Deskbar-Token": "push-token"}, 5),
    ]
    return result


def test_all_managed_sources_paused_override_legacy_enabled(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=["openai"],
        registry_sources=[
            {
                "source_id": "openai-a",
                "provider": "openai",
                "provider_account_id": "acct-a",
                "enabled": False,
                "archived": False,
            },
            {
                "source_id": "openai-b",
                "provider": "openai",
                "provider_account_id": "acct-b",
                "enabled": False,
                "archived": False,
            },
        ],
    )

    assert result == ()


def test_archived_only_sources_override_legacy_enabled(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=["openai"],
        registry_sources=[
            {
                "source_id": "openai-archived",
                "provider": "openai",
                "provider_account_id": "acct-a",
                "enabled": True,
                "archived": True,
            },
        ],
    )

    assert result == ()


def test_enabled_named_source_enables_provider_despite_legacy_disabled(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=[],
        registry_sources=[
            {
                "source_id": "openai-a",
                "provider": "openai",
                "provider_account_id": "acct-a",
                "enabled": False,
                "archived": False,
            },
            {
                "source_id": "openai-b",
                "provider": "openai",
                "provider_account_id": "acct-b",
                "enabled": True,
                "archived": False,
            },
        ],
    )

    assert result == ("openai",)


def test_paused_anonymous_managed_source_overrides_legacy_enabled(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=["openai"],
        registry_sources=[
            {
                "source_id": "openai-anon",
                "provider": "openai",
                "provider_account_id": None,
                "enabled": False,
                "archived": False,
            },
        ],
    )

    assert result == ()


def test_provider_without_managed_records_uses_legacy_prefs(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=["openai"],
        registry_sources=[],
    )

    assert result == ("openai",)


def test_old_server_404_uses_legacy_prefs(monkeypatch):
    result = _fetch_sources(
        monkeypatch,
        legacy_sources=["openai"],
        registry_sources=[],
        status_code=404,
    )

    assert result == ("openai",)
