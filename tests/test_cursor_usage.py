"""Cursor 用量抓取：純解析、憑證讀取失敗、HTTP 各種回應。

一律用注入的假 client 與假 runner——不准真的跑 security 指令、不准真的打網路。
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("cursor_usage", TOOLS_DIR / "cursor_usage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _jwt(sub="google-oauth2|user_TEST"):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"


REAL_SUMMARY = {
    "billingCycleStart": "2026-08-17T10:41:32.000Z",
    "billingCycleEnd": "2026-09-17T10:41:32.000Z",
    "membershipType": "pro",
    "isUnlimited": False,
    "individualUsage": {"plan": {"enabled": True, "used": 2000, "limit": 2000,
                                 "totalPercentUsed": 100}},
}


class _Runner:
    def __init__(self, returncode=0, stdout=_jwt()):
        self.returncode, self.stdout = returncode, stdout

    def __call__(self, *a, **kw):
        return self


class _Resp:
    def __init__(self, status_code=200, data=None, bad_json=False):
        self.status_code, self._data, self._bad = status_code, data, bad_json

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._data


class _HTTP:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_parse_usage_summary_reads_pct_and_reset():
    cu = _load()
    r = cu.parse_usage_summary(REAL_SUMMARY)
    assert r["used_pct"] == 100.0
    assert r["resets_at"] == "2026-09-17T10:41:32.000Z"
    assert r["plan"] == "pro"


@pytest.mark.parametrize("data", [
    None, {}, "nope", {"individualUsage": None},
    {"individualUsage": {"plan": {"totalPercentUsed": "abc"}}},
    {"individualUsage": {"plan": {"totalPercentUsed": 140}}},
    {"individualUsage": {"plan": {"totalPercentUsed": -1}}},
])
def test_parse_usage_summary_bad_input_gives_none(data):
    cu = _load()
    assert cu.parse_usage_summary(data)["used_pct"] is None


def test_fetch_usage_success_sends_origin_and_cookie():
    cu = _load()
    http = _HTTP(_Resp(200, REAL_SUMMARY))
    r = cu.fetch_usage(http=http, runner=_Runner())
    assert r["used_pct"] == 100.0
    headers = http.calls[0][1]["headers"]
    assert headers["Origin"] == "https://cursor.com"
    assert headers["Referer"] == "https://cursor.com/dashboard"
    assert headers["Cookie"].startswith("WorkosCursorSessionToken=")
    assert "%3A%3A" in headers["Cookie"]


def test_fetch_usage_403_returns_none():
    cu = _load()
    assert cu.fetch_usage(http=_HTTP(_Resp(403, {})), runner=_Runner()) is None


def test_fetch_usage_bad_json_returns_none():
    cu = _load()
    assert cu.fetch_usage(http=_HTTP(_Resp(200, None, bad_json=True)), runner=_Runner()) is None


def test_load_token_returns_none_when_security_fails():
    cu = _load()
    assert cu.load_token(runner=_Runner(returncode=1, stdout="")) is None
    assert cu.fetch_usage(http=_HTTP(_Resp(200, REAL_SUMMARY)),
                          runner=_Runner(returncode=1, stdout="")) is None


def test_fetch_usage_none_when_token_is_not_a_jwt():
    cu = _load()
    assert cu.fetch_usage(http=_HTTP(_Resp(200, REAL_SUMMARY)),
                          runner=_Runner(stdout="not-a-jwt")) is None
