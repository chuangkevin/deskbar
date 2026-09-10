"""tools 下 usage 推送與用量抓取工具測試。"""
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


def test_openai_usage_compiles():
    _compile("openai_usage.py")


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


def test_ag_payload_fields_normal_conversion():
    from datetime import datetime, timezone, timedelta
    demo = _load_demo_module()

    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    parsed = {
        "gemini_5h_remaining": 64.24,
        "gemini_5h_refresh_min": 89,
        "gemini_weekly_remaining": 94.04,
        "gemini_weekly_refresh_min": 9869,
    }

    res = demo.ag_payload_fields(parsed, now)

    assert res["ag_5h_pct"] == pytest.approx(35.76)
    assert res["ag_5h_resets_at"] == (now + timedelta(minutes=89)).isoformat()
    assert res["ag_weekly_pct"] == pytest.approx(5.96)
    assert res["ag_weekly_resets_at"] == (now + timedelta(minutes=9869)).isoformat()


def test_ag_payload_fields_all_none_input():
    from datetime import datetime, timezone
    demo = _load_demo_module()

    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    parsed = {
        "gemini_5h_remaining": None,
        "gemini_5h_refresh_min": None,
        "gemini_weekly_remaining": None,
        "gemini_weekly_refresh_min": None,
    }

    res = demo.ag_payload_fields(parsed, now)

    assert set(res.keys()) == {
        "ag_5h_pct",
        "ag_5h_resets_at",
        "ag_weekly_pct",
        "ag_weekly_resets_at",
    }
    assert all(val is None for val in res.values())

    res_empty = demo.ag_payload_fields({}, now)
    assert set(res_empty.keys()) == {
        "ag_5h_pct",
        "ag_5h_resets_at",
        "ag_weekly_pct",
        "ag_weekly_resets_at",
    }
    assert all(val is None for val in res_empty.values())


def test_ag_payload_fields_partially_filled():
    from datetime import datetime, timezone, timedelta
    demo = _load_demo_module()

    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    parsed = {
        "gemini_5h_remaining": 40.0,
        "gemini_5h_refresh_min": 30,
        "gemini_weekly_remaining": None,
        "gemini_weekly_refresh_min": None,
    }

    res = demo.ag_payload_fields(parsed, now)

    assert res["ag_5h_pct"] == pytest.approx(60.0)
    assert res["ag_5h_resets_at"] == (now + timedelta(minutes=30)).isoformat()
    assert res["ag_weekly_pct"] is None
    assert res["ag_weekly_resets_at"] is None


def test_build_payload_includes_ag_fields(monkeypatch):
    demo = _load_demo_module()

    fake_ag = {
        "ag_5h_pct": 25.0,
        "ag_5h_resets_at": "2026-08-04T15:00:00+00:00",
        "ag_weekly_pct": 10.0,
        "ag_weekly_resets_at": "2026-08-10T00:00:00+00:00",
    }
    monkeypatch.setattr(demo, "get_antigravity_fields", lambda: fake_ag)

    usage = {
        "five_hour": {"utilization": 12, "resets_at": "2026-08-04T04:00:00Z"},
        "seven_day": {"utilization": 34, "resets_at": "2026-08-10T00:00:00Z"},
    }

    payload = demo.build_payload(usage, enable_antigravity=True)

    assert payload["session_pct"] == 12
    assert payload["weekly_pct"] == 34
    assert payload["ag_5h_pct"] == 25.0
    assert payload["ag_5h_resets_at"] == "2026-08-04T15:00:00+00:00"
    assert payload["ag_weekly_pct"] == 10.0
    assert payload["ag_weekly_resets_at"] == "2026-08-10T00:00:00+00:00"

    payload_no_ag = demo.build_payload(usage, enable_antigravity=False)
    assert "ag_5h_pct" not in payload_no_ag


def test_oa_payload_fields_normal_conversion():
    from datetime import datetime, timezone
    demo = _load_demo_module()

    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    parsed = {
        "used_pct": 3.0,
        "resets_at_epoch": 1786932438,
        "plan": "prolite",
    }

    res = demo.oa_payload_fields(parsed, now)

    assert res["oa_weekly_pct"] == pytest.approx(3.0)
    assert res["oa_weekly_resets_at"] == datetime.fromtimestamp(
        1786932438, tz=timezone.utc
    ).isoformat()


def test_oa_payload_fields_accounts_keeps_legacy_first():
    from datetime import datetime, timezone
    demo = _load_demo_module()

    now = datetime(2026, 9, 10, 16, 0, 0, tzinfo=timezone.utc)
    first_reset = 1789435507
    second_reset = 1789436507

    res = demo.oa_payload_fields([
        {
            "account_id": "882254a5-first",
            "name": "kevin.systemcom",
            "used_pct": 100,
            "resets_at_epoch": first_reset,
        },
        {
            "account_id": "882254a5-second",
            "name": "interagent.dev01",
            "used_pct": 18,
            "resets_at_epoch": second_reset,
        },
    ], now)

    assert len(res["oa_accounts"]) == 2
    assert res["oa_accounts"][0] == {
        "account_id": "882254a5-first",
        "name": "kevin.systemcom",
        "weekly_pct": 100.0,
        "weekly_resets_at": datetime.fromtimestamp(
            first_reset, tz=timezone.utc
        ).isoformat(),
        "fetched_at": now.isoformat(),
    }
    assert res["oa_accounts"][1]["weekly_pct"] == 18.0
    assert res["oa_accounts"][1]["weekly_resets_at"] == datetime.fromtimestamp(
        second_reset, tz=timezone.utc
    ).isoformat()
    assert res["oa_weekly_pct"] == 100.0
    assert res["oa_weekly_resets_at"] == res["oa_accounts"][0]["weekly_resets_at"]
    assert res["oa_account_id"] == "882254a5-first"
    assert res["oa_fetched_at"] == now.isoformat()


def test_oa_payload_fields_all_none_input():
    from datetime import datetime, timezone
    demo = _load_demo_module()

    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    parsed = {"used_pct": None, "resets_at_epoch": None, "plan": None}

    res = demo.oa_payload_fields(parsed, now)

    assert set(res.keys()) == {"oa_weekly_pct", "oa_weekly_resets_at"}
    assert all(val is None for val in res.values())

    res_empty = demo.oa_payload_fields({}, now)
    assert set(res_empty.keys()) == {"oa_weekly_pct", "oa_weekly_resets_at"}
    assert all(val is None for val in res_empty.values())


def test_build_payload_includes_openai_fields(monkeypatch):
    demo = _load_demo_module()

    fake_oa = {
        "oa_weekly_pct": 3.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
    }
    monkeypatch.setattr(demo, "fetch_openai_usage", object())
    monkeypatch.setattr(demo, "get_openai_fields", lambda: fake_oa)

    usage = {
        "five_hour": {"utilization": 12, "resets_at": "2026-08-04T04:00:00Z"},
        "seven_day": {"utilization": 34, "resets_at": "2026-08-10T00:00:00Z"},
    }

    payload = demo.build_payload(usage, enable_antigravity=False, enable_openai=True)

    assert payload["oa_weekly_pct"] == 3.0
    assert payload["oa_weekly_resets_at"] == "2026-08-17T00:00:00+00:00"

    payload_no_oa = demo.build_payload(usage, enable_antigravity=False, enable_openai=False)
    assert "oa_weekly_pct" not in payload_no_oa


def test_build_payload_includes_openai_accounts_with_legacy_first(monkeypatch):
    demo = _load_demo_module()

    fake_oa = {
        "oa_accounts": [
            {
                "account_id": "account-a",
                "name": "kevin.systemcom",
                "weekly_pct": 100.0,
                "weekly_resets_at": "2026-09-15T09:25:07+08:00",
                "fetched_at": "2026-09-10T16:00:00+08:00",
            },
            {
                "account_id": "account-b",
                "name": "interagent.dev01",
                "weekly_pct": 18.0,
                "weekly_resets_at": "2026-09-15T10:25:07+08:00",
                "fetched_at": "2026-09-10T16:00:00+08:00",
            },
        ],
        "oa_weekly_pct": 100.0,
        "oa_weekly_resets_at": "2026-09-15T09:25:07+08:00",
        "oa_account_id": "account-a",
        "oa_fetched_at": "2026-09-10T16:00:00+08:00",
    }
    monkeypatch.setattr(demo, "fetch_openai_usage", object())
    monkeypatch.setattr(demo, "get_openai_fields", lambda: fake_oa)

    usage = {
        "five_hour": {"utilization": 12, "resets_at": "2026-08-04T04:00:00Z"},
        "seven_day": {"utilization": 34, "resets_at": "2026-08-10T00:00:00Z"},
    }

    payload = demo.build_payload(usage, enable_antigravity=False, enable_openai=True)

    assert payload["oa_accounts"] == fake_oa["oa_accounts"]
    assert len(payload["oa_accounts"]) == 2
    assert payload["oa_weekly_pct"] == payload["oa_accounts"][0]["weekly_pct"]
    assert payload["oa_weekly_resets_at"] == payload["oa_accounts"][0]["weekly_resets_at"]
    assert payload["oa_account_id"] == payload["oa_accounts"][0]["account_id"]
    assert payload["oa_fetched_at"] == payload["oa_accounts"][0]["fetched_at"]


def test_summary_formats_openai_accounts():
    demo = _load_demo_module()

    summary = demo._summary({
        "session_pct": 1,
        "weekly_pct": 2,
        "fable_pct": 3,
        "oa_accounts": [
            {"name": "kevin.systemcom", "weekly_pct": 100.0},
            {"name": "interagent.dev01", "weekly_pct": 18.0},
        ],
    })

    assert "OpenAI kevin.systemcom 100.0% / interagent.dev01 18.0%" in summary


def test_refresh_antigravity_async_keeps_old_value_on_failure(monkeypatch):
    demo = _load_demo_module()

    initial_ag = {
        "ag_5h_pct": 50.0,
        "ag_5h_resets_at": "2026-08-04T12:00:00+00:00",
        "ag_weekly_pct": 20.0,
        "ag_weekly_resets_at": "2026-08-10T12:00:00+00:00",
    }
    with demo._AG_LOCK:
        demo._AG_LATEST.update(initial_ag)

    monkeypatch.setattr(demo, "fetch_usage_text", lambda *a, **kw: None)

    t = demo.refresh_antigravity_async()
    if t is not None:
        t.join()

    assert demo.get_antigravity_fields() == initial_ag

    # 抓到文字但解析全空時也要保留舊值。
    monkeypatch.setattr(demo, "fetch_usage_text", lambda *a, **kw: "some text")
    monkeypatch.setattr(
        demo,
        "parse_usage_panel",
        lambda text: {
            "gemini_5h_remaining": None,
            "gemini_5h_refresh_min": None,
            "gemini_weekly_remaining": None,
            "gemini_weekly_refresh_min": None,
        },
    )

    t = demo.refresh_antigravity_async()
    if t is not None:
        t.join()

    assert demo.get_antigravity_fields() == initial_ag


def test_refresh_openai_async_keeps_old_value_on_failure(monkeypatch):
    demo = _load_demo_module()

    initial_oa = {
        "oa_accounts": [
            {
                "account_id": "account-old",
                "name": "old.account",
                "weekly_pct": 3.0,
                "weekly_resets_at": "2026-08-17T00:00:00+00:00",
                "fetched_at": "2026-08-10T17:00:00+00:00",
            }
        ],
        "oa_weekly_pct": 3.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_account_id": "account-old",
        "oa_fetched_at": "2026-08-10T17:00:00+00:00",
    }
    with demo._OA_LOCK:
        demo._OA_LATEST.update(initial_oa)

    monkeypatch.setattr(demo, "fetch_openai_usage", lambda *a, **kw: None)
    monkeypatch.setattr(demo.time, "monotonic", lambda: 1000.0)

    t = demo.refresh_openai_async()
    if t is not None:
        t.join()

    assert demo.get_openai_fields() == initial_oa


def test_refresh_openai_async_keeps_old_value_when_all_accounts_fail(monkeypatch):
    demo = _load_demo_module()

    initial_oa = {
        "oa_accounts": [
            {
                "account_id": "account-old",
                "name": "old.account",
                "weekly_pct": 3.0,
                "weekly_resets_at": "2026-08-17T00:00:00+00:00",
                "fetched_at": "2026-08-10T17:00:00+00:00",
            }
        ],
        "oa_weekly_pct": 3.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_account_id": "account-old",
        "oa_fetched_at": "2026-08-10T17:00:00+00:00",
    }
    with demo._OA_LOCK:
        demo._OA_LATEST.update(initial_oa)

    monkeypatch.setattr(demo, "fetch_openai_usage", lambda *a, **kw: [])
    monkeypatch.setattr(demo.time, "monotonic", lambda: 1000.0)

    t = demo.refresh_openai_async()
    if t is not None:
        t.join()

    assert demo.get_openai_fields() == initial_oa


def test_refresh_openai_async_min_interval(monkeypatch):
    demo = _load_demo_module()
    calls = []

    def fake_fetch():
        calls.append(True)
        return {"used_pct": 3.0, "resets_at_epoch": 1786932438, "plan": "prolite"}

    monkeypatch.setattr(demo, "fetch_openai_usage", fake_fetch)
    monkeypatch.setattr(demo.time, "monotonic", lambda: 1000.0)

    first = demo.refresh_openai_async()
    if first is not None:
        first.join()
    second = demo.refresh_openai_async()

    assert first is not None
    assert second is None
    assert len(calls) == 1


def test_latest_oa_activity_mtime_uses_newest_existing_path(tmp_path):
    demo = _load_demo_module()
    older = tmp_path / "auth.json"
    newer = tmp_path / "history.jsonl"
    older.touch()
    newer.touch()
    older_mtime = 1000.0
    newer_mtime = 2000.0
    import os
    os.utime(older, (older_mtime, older_mtime))
    os.utime(newer, (newer_mtime, newer_mtime))

    assert demo._latest_oa_activity_mtime(
        (older, newer, tmp_path / "missing"),
        glob_patterns=(),
    ) == newer_mtime


def test_latest_oa_activity_mtime_skips_missing_paths(tmp_path):
    demo = _load_demo_module()

    assert demo._latest_oa_activity_mtime(
        (tmp_path / "missing-a", tmp_path / "missing-b"),
        glob_patterns=(),
    ) is None


@pytest.fixture(autouse=True)
def reset_ag_latest():
    demo = _load_demo_module()
    clean_state = {
        "ag_5h_pct": None,
        "ag_5h_resets_at": None,
        "ag_weekly_pct": None,
        "ag_weekly_resets_at": None,
    }
    with demo._AG_LOCK:
        demo._AG_LATEST.update(clean_state)
    yield
    with demo._AG_LOCK:
        demo._AG_LATEST.update(clean_state)


def test_save_cache_includes_ag_fields(tmp_path):
    demo = _load_demo_module()
    path = tmp_path / "usage.json"
    payload = {
        "session_pct": 42.0,
        "weekly_pct": 10.0,
        "ag_5h_pct": 35.5,
        "ag_5h_resets_at": "2026-08-04T18:00:00+00:00",
        "ag_weekly_pct": 12.0,
        "ag_weekly_resets_at": "2026-08-11T00:00:00+00:00",
        "fetched_at": "2026-08-04T17:00:00+00:00",
    }
    demo.save_cache(payload, path)
    loaded = demo.load_cache(path)
    assert loaded["ag_5h_pct"] == 35.5
    assert loaded["ag_5h_resets_at"] == "2026-08-04T18:00:00+00:00"
    assert loaded["ag_weekly_pct"] == 12.0
    assert loaded["ag_weekly_resets_at"] == "2026-08-11T00:00:00+00:00"


def test_save_cache_includes_openai_fields(tmp_path):
    demo = _load_demo_module()
    path = tmp_path / "usage.json"
    payload = {
        "session_pct": 42.0,
        "weekly_pct": 10.0,
        "oa_weekly_pct": 3.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "fetched_at": "2026-08-10T17:00:00+00:00",
    }
    demo.save_cache(payload, path)
    loaded = demo.load_cache(path)
    assert loaded["oa_weekly_pct"] == 3.0
    assert loaded["oa_weekly_resets_at"] == "2026-08-17T00:00:00+00:00"


def test_warm_ag_from_cache_with_ag_fields():
    demo = _load_demo_module()
    cached = {
        "session_pct": 42.0,
        "ag_5h_pct": 50.0,
        "ag_5h_resets_at": "2026-08-04T18:00:00+00:00",
        "ag_weekly_pct": 25.0,
        "ag_weekly_resets_at": "2026-08-11T00:00:00+00:00",
    }
    demo.warm_ag_from_cache(cached)
    fields = demo.get_antigravity_fields()
    assert fields["ag_5h_pct"] == 50.0
    assert fields["ag_5h_resets_at"] == "2026-08-04T18:00:00+00:00"
    assert fields["ag_weekly_pct"] == 25.0
    assert fields["ag_weekly_resets_at"] == "2026-08-11T00:00:00+00:00"


def test_warm_openai_from_cache_with_openai_fields():
    demo = _load_demo_module()
    cached = {
        "session_pct": 42.0,
        "oa_accounts": [
            {
                "account_id": "account-a",
                "name": "kevin.systemcom",
                "weekly_pct": 3.0,
                "weekly_resets_at": "2026-08-17T00:00:00+00:00",
                "fetched_at": "2026-08-10T17:00:00+00:00",
            }
        ],
        "oa_weekly_pct": 3.0,
        "oa_weekly_resets_at": "2026-08-17T00:00:00+00:00",
        "oa_account_id": "account-a",
        "oa_fetched_at": "2026-08-10T17:00:00+00:00",
    }
    demo.warm_openai_from_cache(cached)
    fields = demo.get_openai_fields()
    assert fields["oa_accounts"] == cached["oa_accounts"]
    assert fields["oa_weekly_pct"] == 3.0
    assert fields["oa_weekly_resets_at"] == "2026-08-17T00:00:00+00:00"
    assert fields["oa_account_id"] == "account-a"
    assert fields["oa_fetched_at"] == "2026-08-10T17:00:00+00:00"


def test_warm_ag_from_cache_missing_fields_defaults_none():
    demo = _load_demo_module()
    cached = {
        "session_pct": 42.0,
        "ag_5h_pct": 50.0,
    }
    demo.warm_ag_from_cache(cached)
    fields = demo.get_antigravity_fields()
    assert fields["ag_5h_pct"] == 50.0
    assert fields["ag_5h_resets_at"] is None
    assert fields["ag_weekly_pct"] is None
    assert fields["ag_weekly_resets_at"] is None


def test_warm_ag_from_cache_none_and_empty_safe_noop():
    demo = _load_demo_module()
    demo.warm_ag_from_cache(None)
    assert demo.get_antigravity_fields() == {
        "ag_5h_pct": None,
        "ag_5h_resets_at": None,
        "ag_weekly_pct": None,
        "ag_weekly_resets_at": None,
    }

    demo.warm_ag_from_cache({})
    assert demo.get_antigravity_fields() == {
        "ag_5h_pct": None,
        "ag_5h_resets_at": None,
        "ag_weekly_pct": None,
        "ag_weekly_resets_at": None,
    }


@pytest.fixture(autouse=True)
def reset_token_refresh_state():
    """測試之間重設 trigger_token_refresh 的上次觸發時間，避免測試間互相污染。"""
    demo = _load_demo_module()
    demo._last_refresh_time = 0.0
    yield
    demo._last_refresh_time = 0.0


def test_trigger_token_refresh_claude_bin_not_found(monkeypatch):
    """CLAUDE_BIN 不存在時回傳 False，且不跑 subprocess。"""
    demo = _load_demo_module()
    monkeypatch.setattr(demo, "CLAUDE_BIN", "/nonexistent/path/to/claude")
    assert demo.trigger_token_refresh() is False


def test_trigger_token_refresh_cooldown(monkeypatch, tmp_path):
    """冷卻期內第二次呼叫回傳 False，且沒有再跑 subprocess。"""
    import subprocess
    demo = _load_demo_module()
    dummy_claude = tmp_path / "claude"
    dummy_claude.touch()
    monkeypatch.setattr(demo, "CLAUDE_BIN", str(dummy_claude))

    calls = []

    def fake_run(cmd, capture_output=True, text=True, timeout=120):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)

    # 第一次觸發成功
    assert demo.trigger_token_refresh() is True
    assert len(calls) == 1

    # 冷卻期內第二次觸發直接回傳 False，不重複跑 subprocess
    assert demo.trigger_token_refresh() is False
    assert len(calls) == 1


def test_trigger_token_refresh_subprocess_exception(monkeypatch, tmp_path):
    """subprocess 拋出例外時吞掉例外並回傳 False。"""
    demo = _load_demo_module()
    dummy_claude = tmp_path / "claude"
    dummy_claude.touch()
    monkeypatch.setattr(demo, "CLAUDE_BIN", str(dummy_claude))

    def fake_run_raise(cmd, capture_output=True, text=True, timeout=120):
        raise FileNotFoundError("claude execution failed")

    monkeypatch.setattr(demo.subprocess, "run", fake_run_raise)

    # 不得拋出例外，應回傳 False
    assert demo.trigger_token_refresh() is False


def test_load_access_token_expired_refresh_success(monkeypatch):
    """load_access_token 遇到過期 token 且換發成功（第二次讀 Keychain 為新 token）時，回傳新 token。"""
    import json
    import subprocess
    import time
    demo = _load_demo_module()

    keychain_responses = [
        json.dumps({"claudeAiOauth": {"accessToken": "old_expired", "expiresAt": 1000}}),
        json.dumps({"claudeAiOauth": {"accessToken": "new_fresh", "expiresAt": (time.time() + 3600) * 1000}}),
    ]

    def fake_run(cmd, capture_output=True, text=True, timeout=30):
        if cmd[0] == "security":
            stdout = keychain_responses.pop(0)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")
        raise RuntimeError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)

    refresh_calls = []

    def fake_trigger():
        refresh_calls.append(True)
        return True

    monkeypatch.setattr(demo, "trigger_token_refresh", fake_trigger)

    token = demo.load_access_token()
    assert token == "new_fresh"
    assert len(refresh_calls) == 1


def test_load_access_token_expired_refresh_failed(monkeypatch):
    """load_access_token 遇到過期 token 且換發失敗時，拋出 SystemExit。"""
    import json
    import subprocess
    demo = _load_demo_module()

    expired_stdout = json.dumps({"claudeAiOauth": {"accessToken": "old_expired", "expiresAt": 1000}})

    def fake_run(cmd, capture_output=True, text=True, timeout=30):
        if cmd[0] == "security":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=expired_stdout, stderr="")
        raise RuntimeError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    monkeypatch.setattr(demo, "trigger_token_refresh", lambda: False)

    with pytest.raises(SystemExit) as exc_info:
        demo.load_access_token()
    assert "token 已過期且自動換發失敗" in str(exc_info.value)


def test_load_access_token_expired_still_expired_no_infinite_loop(monkeypatch):
    """load_access_token 遇到過期 token 且換發後重讀仍過期時，拋出 SystemExit 且 trigger_token_refresh 只呼叫一次。"""
    import json
    import subprocess
    demo = _load_demo_module()

    expired_stdout = json.dumps({"claudeAiOauth": {"accessToken": "old_expired", "expiresAt": 1000}})

    def fake_run(cmd, capture_output=True, text=True, timeout=30):
        if cmd[0] == "security":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=expired_stdout, stderr="")
        raise RuntimeError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)

    refresh_calls = []

    def fake_trigger():
        refresh_calls.append(True)
        return True

    monkeypatch.setattr(demo, "trigger_token_refresh", fake_trigger)

    with pytest.raises(SystemExit) as exc_info:
        demo.load_access_token()
    assert "token 已過期且自動換發失敗" in str(exc_info.value)
    assert len(refresh_calls) == 1
