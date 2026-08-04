"""tools/usage_push_snippet.py 與 tools/usage_push_demo.py：兩支都是 Mac 端
獨立工具，不隨 deskbar 主程式跑，只需要 py_compile 過關；push_to_deskbar() 額外
用 fake requests.post 驗證成功/失敗兩條路徑都不拋例外。"""
import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


def _compile(name: str):
    import py_compile
    py_compile.compile(str(TOOLS_DIR / name), doraise=True)


def test_usage_push_snippet_compiles():
    _compile("usage_push_snippet.py")


def test_usage_push_demo_compiles():
    _compile("usage_push_demo.py")


def _load_snippet_module():
    """獨立載入 usage_push_snippet.py（不在 deskbar package 底下，走檔案路徑載入）。"""
    path = TOOLS_DIR / "usage_push_snippet.py"
    spec = importlib.util.spec_from_file_location("usage_push_snippet", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_demo_module():
    path = TOOLS_DIR / "usage_push_demo.py"
    spec = importlib.util.spec_from_file_location("usage_push_demo", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def snippet():
    return _load_snippet_module()


class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_push_to_deskbar_success_sends_expected_request(snippet, monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers, timeout))
        return FakeResp(204)

    monkeypatch.setattr(snippet.requests, "post", fake_post)
    snippet.push_to_deskbar({"session_pct": 42.0}, "http://deskbar.local:8080/api/usage",
                            token="tok123")

    assert len(calls) == 1
    url, body, headers, timeout = calls[0]
    assert url == "http://deskbar.local:8080/api/usage"
    assert body == {"session_pct": 42.0}
    assert headers == {"X-Deskbar-Token": "tok123"}
    assert timeout == 5


def test_push_to_deskbar_without_token_sends_no_header(snippet, monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(headers)
        return FakeResp(204)

    monkeypatch.setattr(snippet.requests, "post", fake_post)
    snippet.push_to_deskbar({"session_pct": 42.0}, "http://deskbar.local:8080/api/usage")
    assert calls == [{}]


def test_push_to_deskbar_network_error_does_not_raise(snippet, monkeypatch, capsys):
    def fake_post(url, json=None, headers=None, timeout=None):
        raise snippet.requests.RequestException("boom")

    monkeypatch.setattr(snippet.requests, "post", fake_post)
    snippet.push_to_deskbar({"session_pct": 42.0}, "http://deskbar.local:8080/api/usage")
    assert "推送 deskbar 失敗" in capsys.readouterr().out


def test_push_to_deskbar_non_204_prints_warning_does_not_raise(snippet, monkeypatch, capsys):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResp(400, text="invalid session_pct")

    monkeypatch.setattr(snippet.requests, "post", fake_post)
    snippet.push_to_deskbar({"session_pct": 999}, "http://deskbar.local:8080/api/usage")
    out = capsys.readouterr().out
    assert "HTTP 400" in out


def test_usage_demo_cache_round_trip(tmp_path):
    demo = _load_demo_module()
    path = tmp_path / "usage.json"
    payload = {"session_pct": 42.0, "fetched_at": "2026-08-04T01:00:00+00:00"}

    demo.save_cache(payload, path)

    assert demo.load_cache(path) == payload


def test_usage_demo_payload_contains_fetch_timestamp():
    demo = _load_demo_module()
    payload = demo.build_payload({
        "five_hour": {"utilization": 12, "resets_at": "2026-08-04T04:00:00Z"},
        "seven_day": {"utilization": 34, "resets_at": "2026-08-10T00:00:00Z"},
        "limits": [{"kind": "weekly_scoped", "percent": 5, "resets_at": None}],
    })

    assert payload["session_pct"] == 12
    assert payload["weekly_pct"] == 34
    assert payload["fable_pct"] == 5
    assert "+00:00" in payload["fetched_at"]


def test_usage_demo_rate_limit_uses_retry_after(monkeypatch):
    demo = _load_demo_module()

    class Response:
        status_code = 429
        headers = {"Retry-After": "720"}

    monkeypatch.setattr(demo.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(demo.RateLimitedError) as caught:
        demo.fetch_usage("token")
    assert caught.value.retry_after == 720.0
