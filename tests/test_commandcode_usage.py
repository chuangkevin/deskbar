"""CommandCode 用量抓取：key 順序、純解析、HTTP 各種回應。不打網路、不跑真實 ssh、不碰真實家目錄。"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("commandcode_usage", TOOLS_DIR / "commandcode_usage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


REAL = {
    "credits": {"monthlyCredits": 45.07, "purchasedCredits": 0, "freeCredits": 0},
    "windowLimits": {
        "limited": True,
        "fiveHour": {"used": 0.5715, "cap": 14, "exceeded": False, "resetAt": 1790057273729},
        "weekly":   {"used": 24.922, "cap": 35, "exceeded": False, "resetAt": 1790357709248},
    },
}


class _Resp:
    def __init__(self, status_code=200, data=None, bad=False):
        self.status_code, self._d, self._bad = status_code, data, bad

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._d


class _HTTP:
    def __init__(self, resp, sub_resp=None, whoami_resp=None):
        self.resp, self.calls = resp, []
        self.sub_resp = sub_resp if sub_resp is not None else _Resp(500, {})
        # whoami 預設回合法身分（既有測試不斷言 account_id，不受影響）
        if whoami_resp is not None:
            self.whoami_resp = whoami_resp
        else:
            self.whoami_resp = _Resp(200, {"user": {"id": "user_test", "userName": "test-user"}})

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if "subscriptions" in url:
            return self.sub_resp
        if "whoami" in url:
            return self.whoami_resp
        return self.resp


class _FakeRunner:
    def __init__(self, returncode=0, stdout="", raises=False):
        self.returncode = returncode
        self.stdout = stdout
        self.raises = raises
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises:
            raise RuntimeError("ssh failed")
        return self


# ---------------------------------------------------------------- parse_usage

def test_parse_usage_real_response():
    cc = _load()
    r = cc.parse_usage(REAL)
    assert abs(r["five_hour_pct"] - 4.08214) < 0.01
    assert abs(r["weekly_pct"] - 71.2057) < 0.01
    assert r["five_hour_resets_at"] == datetime.fromtimestamp(1790057273729 / 1000.0, tz=timezone.utc)
    assert r["weekly_resets_at"] == datetime.fromtimestamp(1790357709248 / 1000.0, tz=timezone.utc)
    assert r["monthly_credits"] == 45.07


def test_parse_usage_cap_zero():
    cc = _load()
    data = {
        "windowLimits": {
            "limited": True,
            "fiveHour": {"used": 0.5, "cap": 0, "exceeded": False, "resetAt": 1790057273729},
            "weekly": {"used": 24.922, "cap": 35, "exceeded": False, "resetAt": 1790357709248},
        }
    }
    r = cc.parse_usage(data)
    assert r["five_hour_pct"] is None
    assert abs(r["weekly_pct"] - 71.2057) < 0.01


def test_parse_usage_missing_window_limits():
    cc = _load()
    data = {"credits": {"monthlyCredits": 45.07}}
    r = cc.parse_usage(data)
    assert r["five_hour_pct"] is None
    assert r["five_hour_resets_at"] is None
    assert r["weekly_pct"] is None
    assert r["weekly_resets_at"] is None
    assert r["monthly_credits"] == 45.07


def test_parse_usage_limited_false():
    cc = _load()
    data = {
        "windowLimits": {
            "limited": False,
            "fiveHour": {"used": 0.5715, "cap": 14, "exceeded": False, "resetAt": 1790057273729},
            "weekly":   {"used": 24.922, "cap": 35, "exceeded": False, "resetAt": 1790357709248},
        }
    }
    r = cc.parse_usage(data)
    assert r["five_hour_pct"] is None
    assert r["weekly_pct"] is None


def test_parse_usage_exceeded_true():
    cc = _load()
    data = {
        "windowLimits": {
            "limited": True,
            "fiveHour": {"used": 21.0, "cap": 14.0, "exceeded": True, "resetAt": 1790057273729},
            "weekly":   {"used": 35.0, "cap": 35.0, "exceeded": False, "resetAt": 1790357709248},
        }
    }
    r = cc.parse_usage(data)
    assert r["five_hour_pct"] == 150.0
    assert r["weekly_pct"] == 100.0


# ---------------------------------------------------------------- load_api_key

def test_load_api_key_from_env(tmp_path):
    cc = _load()
    key_file = tmp_path / "commandcode.key"
    key_file.write_text("file-key", encoding="utf-8")
    env = {"COMMANDCODE_API_KEY": "env-key"}
    runner = _FakeRunner(returncode=0, stdout=json.dumps({"key": "ssh-key"}))
    assert cc.load_api_key(env=env, key_path=key_file, runner=runner, cache_path=tmp_path / "cache.json") == "env-key"
    assert len(runner.calls) == 0


def test_load_api_key_from_local_file(tmp_path):
    cc = _load()
    key_file = tmp_path / "commandcode.key"
    key_file.write_text("  local-key-from-file  \n", encoding="utf-8")
    runner = _FakeRunner(returncode=0, stdout=json.dumps({"key": "ssh-key"}))
    assert cc.load_api_key(env={}, key_path=key_file, runner=runner, cache_path=tmp_path / "cache.json") == "local-key-from-file"
    assert len(runner.calls) == 0


def test_load_api_key_from_ssh_success_writes_cache(tmp_path):
    cc = _load()
    cache_path = tmp_path / "cache.json"
    runner = _FakeRunner(returncode=0, stdout=json.dumps({"key": "ssh-retrieved-key"}))
    assert not cache_path.exists()
    assert cc.load_api_key(env={}, key_path=tmp_path / "missing.key", runner=runner, cache_path=cache_path) == "ssh-retrieved-key"
    assert len(runner.calls) == 1
    assert cache_path.exists()
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["keys"] == ["ssh-retrieved-key"]   # 多帳號後快取存 keys 清單
    assert "fetched_at" in saved
    # Check permissions 0600
    assert (cache_path.stat().st_mode & 0o777) == 0o600


def test_load_api_key_from_ssh_failure_reads_cache(tmp_path):
    cc = _load()
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"key": "cached-fallback-key", "fetched_at": "2026-09-22T00:00:00Z"}), encoding="utf-8")
    runner = _FakeRunner(raises=True)
    assert cc.load_api_key(env={}, key_path=tmp_path / "missing.key", runner=runner, cache_path=cache_path) == "cached-fallback-key"


def test_load_api_key_all_missing_returns_none(tmp_path):
    cc = _load()
    runner = _FakeRunner(returncode=1, stdout="")
    assert cc.load_api_key(env={}, key_path=tmp_path / "missing.key", runner=runner, cache_path=tmp_path / "missing-cache.json") is None


# ---------------------------------------------------------------- fetch_usage

def test_fetch_usage_success(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(200, REAL))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is not None
    assert abs(res["five_hour_pct"] - 4.08214) < 0.01
    # fetch_usage 現在先打 whoami 再打 credits；找 credits 那一次呼叫來驗 header
    url, kw = next(call for call in http.calls if call[0] == cc.USAGE_URL)
    assert kw["headers"]["Authorization"] == "Bearer test-key"
    assert kw["headers"]["Accept"] == "application/json"
    assert kw["timeout"] == 15


def test_fetch_usage_401_returns_none(tmp_path, capsys):
    cc = _load()
    http = _HTTP(_Resp(401, {"error": "unauthorized"}))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is None
    out = capsys.readouterr().out
    assert "[CommandCode] API key 被拒" in out


def test_fetch_usage_500_returns_none(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(500, {}))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is None


def test_fetch_usage_bad_json_returns_none(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(200, None, bad=True))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is None


def test_parse_period_end_normal():
    cc = _load()
    assert cc.parse_period_end(
        {"data": {"currentPeriodEnd": "2026-10-18T17:15:12.000Z"}}
    ) == datetime(2026, 10, 18, 17, 15, 12, tzinfo=timezone.utc)


def test_parse_period_end_bad_returns_none():
    cc = _load()
    assert cc.parse_period_end({}) is None
    assert cc.parse_period_end({"data": {}}) is None
    assert cc.parse_period_end({"data": {"currentPeriodEnd": "not-a-date"}}) is None
    assert cc.parse_period_end(None) is None


def test_fetch_usage_success_includes_period_end(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(200, REAL),
                 _Resp(200, {"data": {"currentPeriodEnd": "2026-10-18T17:15:12.000Z"}}))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is not None
    assert res["period_end"] == datetime(2026, 10, 18, 17, 15, 12, tzinfo=timezone.utc)
    assert abs(res["five_hour_pct"] - 4.08214) < 0.01


def test_fetch_usage_subscriptions_500_keeps_credits(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(200, REAL), _Resp(500, {}))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is not None
    assert res["period_end"] is None
    assert abs(res["five_hour_pct"] - 4.08214) < 0.01


def test_fetch_usage_subscriptions_bad_json_keeps_credits(tmp_path):
    cc = _load()
    http = _HTTP(_Resp(200, REAL), _Resp(200, None, bad=True))
    res = cc.fetch_usage(http=http, env={"COMMANDCODE_API_KEY": "test-key"})
    assert res is not None
    assert res["period_end"] is None
    assert abs(res["weekly_pct"] - 71.2057) < 0.01


# ---------------------------------------------------------------- fetch_account identity / UA

def test_fetch_account_sends_user_agent():
    cc = _load()
    http = _HTTP(_Resp(200, REAL))
    res = cc.fetch_account("test-key", http=http)
    assert res is not None
    urls = {url for url, _ in http.calls}
    assert cc.WHOAMI_URL in urls
    assert cc.USAGE_URL in urls
    assert cc.SUBSCRIPTIONS_URL in urls
    for url, kw in http.calls:
        assert kw["headers"]["User-Agent"] == cc.USER_AGENT


def test_fetch_account_returns_none_when_whoami_fails(capsys):
    cc = _load()
    http = _HTTP(_Resp(200, REAL), whoami_resp=_Resp(403, {"error": "forbidden"}))
    res = cc.fetch_account("user_zjMkey1234567890", http=http)
    assert res is None
    out = capsys.readouterr().out
    assert "[CommandCode] whoami 失敗，略過這把 key（避免產生假帳號）" in out


def test_fetch_account_uses_whoami_identity():
    cc = _load()
    http = _HTTP(
        _Resp(200, REAL),
        whoami_resp=_Resp(200, {"user": {"id": "user_real", "userName": "kevin202511180ysi"}}),
    )
    res = cc.fetch_account("test-key", http=http)
    assert res is not None
    assert res["account_id"] == "user_real"
    assert res["name"] == "kevin202511180ysi"


def test_newapi_remote_script_reads_keys_from_every_enabled_commandcode_channel(tmp_path):
    """2026-09-23 Kevin：New API 另開 CommandCode channel 也要自動出現，不能只讀第一個。"""
    import sqlite3
    import subprocess

    db = tmp_path / "one-api.db"
    conn = sqlite3.connect(db)
    conn.execute("create table channels (id integer, name text, key text, base_url text, status integer)")
    conn.executemany("insert into channels values (?, ?, ?, ?, ?)", [
        (22, "commandcode-goat x3", "k1\nk2\nk3", "https://api.commandcode.ai", 1),
        (30, "commandcode-new", "k4", "https://api.commandcode.ai/", 1),
        (31, "commandcode-off", "k-disabled", "https://api.commandcode.ai", 2),
        (5, "other", "k-other", "https://api.example.com", 1),
        (32, "commandcode-dup", "k2", "https://api.commandcode.ai", 1),
    ])
    conn.commit()
    conn.close()

    m = _load()
    out = subprocess.run([sys.executable, "-"], input=m._newapi_remote_script(str(db)),
                         capture_output=True, text=True, check=True).stdout
    keys = m._flatten_key_items(json.loads(out)["keys"])
    assert keys == ["k1", "k2", "k3", "k4"]


def test_newapi_remote_script_stays_read_only():
    m = _load()
    script = m._newapi_remote_script("/tmp/x.db").lower()
    assert "mode=ro" in script
    for word in ("update ", "insert ", "delete ", "drop "):
        assert word not in script
