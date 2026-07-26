"""deskbar.claudeusage：OAuth token 存取/刷新、usage 解析、倒數格式化、
背景 thread 啟動條件的驗證。所有網路呼叫皆用 fake http_get/http_post 注入，
不打真正的 Anthropic API。"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from deskbar import claudeusage

TZ = ZoneInfo("Asia/Taipei")


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _write_token(monkeypatch, tmp_path, **overrides):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    tok = {
        "access_token": "at1",
        "refresh_token": "rt1",
        "expires_at": 10_000.0,
        "scope": claudeusage.SCOPE,
    }
    tok.update(overrides)
    claudeusage.oauth_path().write_text(json.dumps(tok), encoding="utf-8")
    return tok


# ---------------------------------------------------------------- refresh_if_needed


def test_refresh_not_needed_returns_existing_without_network_call(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=100_000.0)
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(json)
        raise AssertionError("不該打網路——expires_at 遠在未來")

    tok = claudeusage.refresh_if_needed(http_post=post, now_fn=lambda: 0.0)
    assert tok["access_token"] == "at1"
    assert calls == []


def test_refresh_rotates_and_persists_new_token(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=100.0)   # 已在 REFRESH_MARGIN_S 內

    def post(url, json=None, timeout=None):
        assert url == claudeusage.TOKEN_URL
        assert json["grant_type"] == "refresh_token"
        assert json["refresh_token"] == "rt1"
        assert json["client_id"] == claudeusage.CLIENT_ID
        return FakeResp(200, {"access_token": "at2", "refresh_token": "rt2",
                              "expires_in": 3600, "scope": claudeusage.SCOPE})

    tok = claudeusage.refresh_if_needed(http_post=post, now_fn=lambda: 0.0)
    assert tok["access_token"] == "at2"
    assert tok["refresh_token"] == "rt2"
    assert tok["expires_at"] == 3600.0

    persisted = json.loads(claudeusage.oauth_path().read_text(encoding="utf-8"))
    assert persisted["access_token"] == "at2"
    assert persisted["refresh_token"] == "rt2"


def test_refresh_4xx_returns_none_needs_login(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=100.0)

    def post(url, json=None, timeout=None):
        return FakeResp(400, {"error": "invalid_grant"})

    assert claudeusage.refresh_if_needed(http_post=post, now_fn=lambda: 0.0) is None


def test_refresh_no_token_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))

    def post(url, json=None, timeout=None):
        raise AssertionError("沒有 token 檔不該打網路")

    assert claudeusage.refresh_if_needed(http_post=post) is None


def test_refresh_network_error_falls_back_to_stale_token(monkeypatch, tmp_path):
    import requests
    _write_token(monkeypatch, tmp_path, expires_at=100.0)

    def post(url, json=None, timeout=None):
        raise requests.RequestException("timeout")

    tok = claudeusage.refresh_if_needed(http_post=post, now_fn=lambda: 0.0)
    assert tok["access_token"] == "at1"    # 網路暫時失敗：先將就用舊的，不當成需要重新登入


# ---------------------------------------------------------------- fetch_usage


def test_fetch_usage_parses_five_hour_seven_day_and_fable(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=1e12)   # 遠在未來，refresh 不會觸發
    body = {
        "five_hour": {"utilization": 42, "resets_at": "2026-07-27T18:00:00Z"},
        "seven_day": {"utilization": 61.5, "resets_at": "2026-08-02T00:00:00Z"},
        "limits": [
            {"scope": {"model": {"display_name": "Claude Sonnet"}}, "utilization": 5},
            {"scope": {"model": {"display_name": "Claude Fable 5"}}, "utilization": 12,
             "resets_at": "2026-08-02T00:00:00Z"},
        ],
    }

    def get(url, headers=None, timeout=None):
        assert url == claudeusage.USAGE_URL
        assert headers["anthropic-beta"] == claudeusage.USAGE_BETA_HEADER
        assert headers["Authorization"] == "Bearer at1"
        return FakeResp(200, body)

    info = claudeusage.fetch_usage(http_get=get, now_fn=lambda: datetime(2026, 7, 27, tzinfo=TZ))
    assert info.session_pct == 42.0
    assert info.session_resets_at is not None
    assert info.weekly_pct == 61.5
    assert info.fable_pct == 12.0
    assert info.fable_resets_at is not None
    assert info.needs_login is False


def test_fetch_usage_missing_fields_default_none(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=1e12)

    def get(url, headers=None, timeout=None):
        return FakeResp(200, {})   # 整包都缺

    info = claudeusage.fetch_usage(http_get=get)
    assert info.session_pct is None
    assert info.session_resets_at is None
    assert info.weekly_pct is None
    assert info.fable_pct is None
    assert info.fable_resets_at is None
    assert info.needs_login is False


def test_fetch_usage_utilization_zero_is_not_none(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=1e12)

    def get(url, headers=None, timeout=None):
        return FakeResp(200, {"five_hour": {"utilization": 0}, "seven_day": {"utilization": 0}})

    info = claudeusage.fetch_usage(http_get=get)
    assert info.session_pct == 0.0
    assert info.weekly_pct == 0.0


def test_fetch_usage_no_token_needs_login(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))

    def get(url, headers=None, timeout=None):
        raise AssertionError("沒有 token 不該打 usage API")

    info = claudeusage.fetch_usage(http_get=get)
    assert info.needs_login is True
    assert info.session_pct is None


def test_fetch_usage_401_marks_needs_login(monkeypatch, tmp_path):
    _write_token(monkeypatch, tmp_path, expires_at=1e12)

    def get(url, headers=None, timeout=None):
        return FakeResp(401, {"error": "unauthorized"})

    info = claudeusage.fetch_usage(http_get=get)
    assert info.needs_login is True


def test_fetch_usage_network_error_does_not_raise(monkeypatch, tmp_path):
    import requests
    _write_token(monkeypatch, tmp_path, expires_at=1e12)

    def get(url, headers=None, timeout=None):
        raise requests.RequestException("boom")

    info = claudeusage.fetch_usage(http_get=get)
    assert info.needs_login is False
    assert info.session_pct is None


# ---------------------------------------------------------------- fmt_countdown


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


def test_fmt_countdown_days():
    assert claudeusage.fmt_countdown(NOW + timedelta(days=1, hours=4), NOW) == "1d 4h"


def test_fmt_countdown_hours_minutes():
    assert claudeusage.fmt_countdown(NOW + timedelta(hours=2, minutes=3), NOW) == "2h 03m"


def test_fmt_countdown_imminent():
    assert claudeusage.fmt_countdown(NOW + timedelta(seconds=30), NOW) == "即將重置"
    assert claudeusage.fmt_countdown(NOW - timedelta(seconds=5), NOW) == "即將重置"


def test_fmt_countdown_none():
    assert claudeusage.fmt_countdown(None, NOW) == "—"


# ---------------------------------------------------------------- start_usage_thread


def test_start_usage_thread_returns_false_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))

    class DummyState:
        def set_usage(self, info):
            raise AssertionError("不該被呼叫——沒有憑證就不該啟動")

    assert claudeusage.start_usage_thread(DummyState()) is False


def test_start_usage_thread_returns_true_with_credentials(monkeypatch, tmp_path):
    """有憑證檔就該回 True 並真的啟動一條背景 thread；用 _fetch_usage 注入點
    （比照 sync.py 的 _get_token/_fetch_range）避免真的打網路。"""
    _write_token(monkeypatch, tmp_path, expires_at=1e12)
    calls = []
    monkeypatch.setattr(claudeusage, "_fetch_usage",
                        lambda: calls.append(1) or
                        claudeusage._empty_usage(NOW, needs_login=False))

    received = []

    class DummyState:
        def set_usage(self, info):
            received.append(info)

    assert claudeusage.start_usage_thread(DummyState(), interval=3600) is True
    import time as _t
    for _ in range(50):
        if received:
            break
        _t.sleep(0.02)
    assert received, "背景 thread 應該至少呼叫過一次 set_usage"


# ---------------------------------------------------------------- scope 白名單


def test_scope_is_read_only_minimum():
    assert claudeusage.SCOPE == "user:profile"
    assert "create_api_key" not in claudeusage.SCOPE
    assert "inference" not in claudeusage.SCOPE
    assert "write" not in claudeusage.SCOPE
