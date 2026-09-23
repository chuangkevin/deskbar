"""OpenCode Go 用量抓取：key 讀取順序、多 key、純解析、HTTP 各種回應、401/403 略過。

不打網路、不讀真實 key 檔。key 原文絕不出現在斷言以外的地方；
這裡的測試 key 都是假字串。
"""
from __future__ import annotations

import hashlib
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
    """依序回應（多把 key 場景）；記錄每次呼叫的 header。"""

    def __init__(self, resps):
        self.resps = list(resps)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        idx = min(len(self.calls) - 1, len(self.resps) - 1)
        return self.resps[idx]


def test_parse_usage_reads_three_windows():
    og = _load()
    r = og.parse_usage(REAL)
    assert r["rolling_pct"] == 0.0 and r["rolling_resets_at"] == "2026-09-11T07:20:41.409Z"
    assert r["weekly_pct"] == 37.5
    assert r["monthly_pct"] == 12.0
    assert r["monthly_resets_at"] == "2026-10-11T02:10:03.409Z"


@pytest.mark.parametrize("data", [None, {}, "x", {"usage": None}, {"usage": {"weekly": {"percent": "abc"}}}])
def test_parse_usage_bad_input_gives_none(data):
    og = _load()
    r = og.parse_usage(data)
    assert r["weekly_pct"] is None and r["rolling_pct"] is None and r["monthly_pct"] is None


@pytest.mark.parametrize("raw,expected", [(-5, 0.0), (120, 100.0), (100.2, 100.0), (37.5, 37.5)])
def test_parse_usage_out_of_range_is_clamped(raw, expected):
    """百分比超出 0–100 不要丟掉，壓回範圍（全專案規則）。"""
    og = _load()
    r = og.parse_usage({"usage": {"weekly": {"percent": raw, "resetsAt": "x"}}})
    assert r["weekly_pct"] == expected


def test_load_api_keys_env_first(tmp_path):
    og = _load()
    key_file = tmp_path / "opencode.key"
    key_file.write_text("file-key-1\n", encoding="utf-8")
    auth = _auth(tmp_path, "auth-key")
    keys = og.load_api_keys(env={"OPENCODE_GO_API_KEY": "env-key-1,env-key-2"}, key_path=key_file, auth_path=auth)
    assert keys == ["env-key-1", "env-key-2"]


def test_load_api_keys_file_multi_key(tmp_path):
    og = _load()
    key_file = tmp_path / "opencode.key"
    key_file.write_text("k1\n\nk2\nk1\n", encoding="utf-8")
    auth = _auth(tmp_path, "auth-key")
    keys = og.load_api_keys(env={}, key_path=key_file, auth_path=auth)
    assert keys == ["k1", "k2"]


def test_load_api_keys_falls_back_to_auth_json(tmp_path):
    og = _load()
    keys = og.load_api_keys(env={}, key_path=tmp_path / "missing.key", auth_path=_auth(tmp_path, "sk-abc"))
    assert keys == ["sk-abc"]


def test_load_api_keys_nothing_returns_empty(tmp_path):
    og = _load()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert og.load_api_keys(env={}, key_path=tmp_path / "missing.key", auth_path=bad) == []


def test_key_id_is_sha12_not_prefix():
    og = _load()
    key = "sk-test-key-value"
    kid = og.key_id(key)
    assert kid == hashlib.sha256(key.encode()).hexdigest()[:12]
    assert len(kid) == 12
    assert not key.startswith(kid)


def test_fetch_account_sends_bearer_key_and_user_agent():
    og = _load()
    http = _HTTP([_Resp(200, REAL)])
    r = og.fetch_account("sk-abc", http=http)
    assert r["weekly_pct"] == 37.5
    assert r["account_id"] == hashlib.sha256(b"sk-abc").hexdigest()[:12]
    url, kw = http.calls[0]
    assert url == og.USAGE_URL
    assert kw["headers"]["Authorization"] == "Bearer sk-abc"
    assert kw["headers"]["User-Agent"] == og.USER_AGENT


def test_fetch_account_rejected_key_returns_none(capsys):
    """401/403 → None（呼叫端略過這張卡片），且不印 key 原文。"""
    og = _load()
    for status in (401, 403):
        http = _HTTP([_Resp(status, {})])
        assert og.fetch_account("sk-secret-xyz", http=http) is None
        out = capsys.readouterr().out
        assert "[OpenCode] key 被拒" in out
        assert "sk-secret-xyz" not in out


def test_fetch_account_other_failures_return_none():
    og = _load()
    assert og.fetch_account("k", http=_HTTP([_Resp(500, {})])) is None
    assert og.fetch_account("k", http=_HTTP([_Resp(200, None, bad=True)])) is None


def test_fetch_accounts_skips_rejected_but_keeps_others(capsys):
    """兩把 key、一把被拒 → 只回成功那把，其他照常。"""
    og = _load()
    http = _HTTP([_Resp(200, REAL), _Resp(401, {})])
    accounts = og.fetch_accounts(keys=["good-key", "bad-key"], http=http)
    assert len(accounts) == 1
    assert accounts[0]["account_id"] == hashlib.sha256(b"good-key").hexdigest()[:12]
    assert accounts[0]["weekly_pct"] == 37.5


def test_fetch_accounts_no_keys_returns_empty():
    og = _load()
    assert og.fetch_accounts(keys=[]) == []
    assert og.fetch_accounts(keys=[], http=_HTTP([_Resp(200, REAL)])) == []


def test_fetch_usage_uses_first_key():
    og = _load()
    http = _HTTP([_Resp(200, REAL)])
    r = og.fetch_usage(http=http, env={"OPENCODE_GO_API_KEY": "first-key"})
    assert r is not None
    assert r["account_id"] == hashlib.sha256(b"first-key").hexdigest()[:12]
    assert http.calls[0][1]["headers"]["Authorization"] == "Bearer first-key"


def test_fetch_usage_no_key_returns_none(capsys):
    og = _load()
    assert og.fetch_usage(env={}, key_path="/nonexistent/opencode.key",
                          auth_path="/nonexistent/auth.json") is None
    assert "[OpenCode] 抓取失敗：找不到 API key" in capsys.readouterr().out
