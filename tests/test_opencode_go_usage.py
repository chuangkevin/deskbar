"""OpenCode Go 用量抓取：key 讀取、純解析、HTTP 各種回應。不打網路、不讀真實 auth.json。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("opencode_go_usage", TOOLS_DIR / "opencode_go_usage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


REAL = {"usage": {
    "rolling": {"status": "ok", "percent": 0, "resetsAt": "2026-09-11T07:20:41.409Z"},
    "weekly": {"status": "ok", "percent": 37.5, "resetsAt": "2026-09-14T00:00:00.409Z"},
    "monthly": {"status": "ok", "percent": 12, "resetsAt": "2026-10-11T02:10:03.409Z"},
}}


def _auth(tmp_path, key="sk-test"):
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"opencode-go": {"type": "api", "key": key}}), encoding="utf-8")
    return p


class _Resp:
    def __init__(self, status_code=200, data=None, bad=False):
        self.status_code, self._d, self._bad = status_code, data, bad

    def json(self):
        if self._bad:
            raise ValueError("bad")
        return self._d


class _HTTP:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append((url, kw)); return self.resp


def test_parse_usage_reads_three_windows():
    og = _load(); r = og.parse_usage(REAL)
    assert r["rolling_pct"] == 0.0 and r["rolling_resets_at"] == "2026-09-11T07:20:41.409Z"
    assert r["weekly_pct"] == 37.5
    assert r["monthly_pct"] == 12.0


@pytest.mark.parametrize("data", [None, {}, "x", {"usage": None}, {"usage": {"weekly": {"percent": "abc"}}},
                                  {"usage": {"weekly": {"percent": 120}}}])
def test_parse_usage_bad_input_gives_none(data):
    og = _load(); r = og.parse_usage(data)
    assert r["weekly_pct"] is None and r["rolling_pct"] is None


def test_load_api_key_from_auth_json(tmp_path):
    og = _load()
    assert og.load_api_key(_auth(tmp_path, "sk-abc")) == "sk-abc"
    assert og.load_api_key(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"; bad.write_text("{not json", encoding="utf-8")
    assert og.load_api_key(bad) is None
    nokey = tmp_path / "nokey.json"; nokey.write_text(json.dumps({"openai": {}}), encoding="utf-8")
    assert og.load_api_key(nokey) is None


def test_fetch_usage_sends_bearer_key(tmp_path):
    og = _load(); http = _HTTP(_Resp(200, REAL))
    r = og.fetch_usage(auth_path=_auth(tmp_path, "sk-abc"), http=http)
    assert r["weekly_pct"] == 37.5
    url, kw = http.calls[0]
    assert url == og.USAGE_URL
    assert kw["headers"]["Authorization"] == "Bearer sk-abc"


def test_fetch_usage_failures_return_none(tmp_path):
    og = _load()
    assert og.fetch_usage(auth_path=_auth(tmp_path), http=_HTTP(_Resp(401, {}))) is None
    assert og.fetch_usage(auth_path=_auth(tmp_path), http=_HTTP(_Resp(200, None, bad=True))) is None
    assert og.fetch_usage(auth_path=tmp_path / "missing.json", http=_HTTP(_Resp(200, REAL))) is None
