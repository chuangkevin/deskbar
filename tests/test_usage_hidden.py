"""usage_hidden：右欄 section 隱藏偏好（2026-09-23 第 2a 段）。

- apply_hidden：純函數，濾掉指定 key、hidden=None 不濾、不存在 key 不影響
- prefs PATCH/GET：round-trip + 驗證錯誤
- /api/usage：預設濾掉 hidden section；?include_hidden=1 顯示並標 hidden=true
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from deskbar import config
from deskbar.alarms import AlarmStore
from deskbar.claudeusage import UsageInfo
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import usagewidget
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 9, 23, 16, 0, tzinfo=TZ)


def _sections():
    return [
        ("CLAUDE CODE", [("5H SESSION", 1.0, None, 18000)], 0.0, "claude"),
        ("ANTIGRAVITY · GEMINI", [("5H", 2.0, None, 18000)], 0.0, "antigravity"),
        ("CC · KS", [("5H", 3.0, None, 18000)], 0.0, "commandcode:cc1"),
        ("OPENCODE GO", [("5H", 4.0, None, 18000)], 0.0, "opencode:og1"),
    ]


# ---------------------------------------------------------------- apply_hidden


def test_apply_hidden_filters_specified_keys():
    out = usagewidget.apply_hidden(_sections(), ["claude", "opencode:og1"])
    keys = [k for _t, _g, _a, k in out]
    assert "claude" not in keys
    assert "opencode:og1" not in keys
    assert keys == ["antigravity", "commandcode:cc1"]


def test_apply_hidden_none_keeps_all():
    out = usagewidget.apply_hidden(_sections(), None)
    assert [k for _t, _g, _a, k in out] == [
        "claude", "antigravity", "commandcode:cc1", "opencode:og1"]


def test_apply_hidden_unknown_key_doesnt_filter():
    out = usagewidget.apply_hidden(_sections(), ["nonexistent"])
    assert [k for _t, _g, _a, k in out] == [
        "claude", "antigravity", "commandcode:cc1", "opencode:og1"]


def test_apply_hidden_does_not_mutate_input():
    sections = _sections()
    snapshot = list(sections)
    usagewidget.apply_hidden(sections, ["claude"])
    assert sections == snapshot


def test_apply_hidden_strips_whitespace():
    out = usagewidget.apply_hidden(_sections(), ["  claude  "])
    keys = [k for _t, _g, _a, k in out]
    assert "claude" not in keys
    assert keys == ["antigravity", "commandcode:cc1", "opencode:og1"]


def test_apply_hidden_empty_list_keeps_all():
    out = usagewidget.apply_hidden(_sections(), [])
    assert [k for _t, _g, _a, k in out] == [
        "claude", "antigravity", "commandcode:cc1", "opencode:og1"]


# ---------------------------------------------------------------- prefs GET/POST


def _prefs_client(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    saved = []
    app = create_app(AlarmStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: saved.append(1))
    app.config["TESTING"] = True
    client = app.test_client()
    client._settings = settings
    return client, settings


def test_prefs_get_returns_usage_hidden_default(tmp_path, monkeypatch):
    client, _ = _prefs_client(tmp_path, monkeypatch)
    d = client.get("/api/prefs").get_json()
    assert d["usage_hidden"] == []


def test_prefs_post_roundtrips_usage_hidden(tmp_path, monkeypatch):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    r = client.patch("/api/prefs", json={"usage_hidden": ["claude", "openai:abc"]})
    assert r.status_code == 200
    assert settings.usage_hidden == ("claude", "openai:abc")
    d = client.get("/api/prefs").get_json()
    assert d["usage_hidden"] == ["claude", "openai:abc"]


@pytest.mark.parametrize("payload", [
    {"usage_hidden": "claude"},
    {"usage_hidden": ["ok"] * 65},
    {"usage_hidden": [""]},
    {"usage_hidden": ["x" * 81]},
    {"usage_hidden": [123]},
    {"usage_hidden": [True]},
    {"usage_hidden": [None]},
])
def test_prefs_post_rejects_invalid_usage_hidden(tmp_path, monkeypatch, payload):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    before = settings.usage_hidden
    r = client.patch("/api/prefs", json=payload)
    assert r.status_code == 400
    assert settings.usage_hidden == before


def test_prefs_post_accepts_empty_usage_hidden(tmp_path, monkeypatch):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    settings.usage_hidden = ("claude",)
    _ = client.patch("/api/prefs", json={"usage_hidden": []})
    assert settings.usage_hidden == ()


def test_normalize_usage_hidden_trims_dedups_rejects():
    assert config.normalize_usage_hidden([" b ", "a", "b"]) == ("b", "a")
    assert config.normalize_usage_hidden(["x" * 80]) == ("x" * 80,)
    assert config.normalize_usage_hidden("claude") == ()
    assert config.normalize_usage_hidden(["a"] * 65) == ()
    assert config.normalize_usage_hidden([""]) == ()
    assert config.normalize_usage_hidden(["x" * 81]) == ()
    assert config.normalize_usage_hidden([123]) == ()
    assert config.normalize_usage_hidden(None) == ()


def test_settings_roundtrip_usage_hidden(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings(usage_hidden=("opencode:abc", "claude"))
    config.save_settings(s)
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["usage_hidden"] == ["opencode:abc", "claude"]
    loaded = config.load_settings()
    assert loaded.usage_hidden == ("opencode:abc", "claude")


# ---------------------------------------------------------------- /api/usage


def _usage_payload():
    """VALID_PAYLOAD，足以產生一個「claude」section。"""
    return {
        "session_pct": 42.0, "session_resets_at": "2026-09-23T18:00:00Z",
        "weekly_pct": 61.5, "weekly_resets_at": "2026-09-24T00:00:00+00:00",
        "fable_pct": 12.0, "fable_resets_at": "2026-09-24T00:00:00Z",
    }


def _usage_client(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    state = AppState()
    app = create_app(AlarmStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: None,
                     usage_state=state)
    app.config["TESTING"] = True
    client = app.test_client()
    # POST usage data
    client.post("/api/usage", json=_usage_payload())
    return client, settings


def test_get_usage_filters_hidden_by_default(tmp_path, monkeypatch):
    client, settings = _usage_client(tmp_path, monkeypatch)
    settings.usage_hidden = ("claude",)
    r = client.get("/api/usage")
    assert r.status_code == 200
    sections = r.get_json()["sections"]
    keys = [s["key"] for s in sections]
    assert "claude" not in keys


def test_get_usage_include_hidden_shows_hidden_with_flag(tmp_path, monkeypatch):
    client, settings = _usage_client(tmp_path, monkeypatch)
    settings.usage_hidden = ("claude",)
    r = client.get("/api/usage?include_hidden=1")
    assert r.status_code == 200
    sections = r.get_json()["sections"]
    claude_sec = [s for s in sections if s["key"] == "claude"]
    assert len(claude_sec) == 1
    assert claude_sec[0]["hidden"] is True
    # Non-hidden sections should have hidden=False
    for s in sections:
        assert s["hidden"] == (s["key"] == "claude")


def test_get_usage_no_hidden_shows_all_without_hidden_field(tmp_path, monkeypatch):
    client, settings = _usage_client(tmp_path, monkeypatch)
    r = client.get("/api/usage?include_hidden=1")
    assert r.status_code == 200
    sections = r.get_json()["sections"]
    # Without hidden set, no section should be hidden
    for s in sections:
        assert s["hidden"] is False


def test_get_usage_filters_by_key_from_prefs_patch(tmp_path, monkeypatch):
    """End-to-end: PATCH usage_hidden -> GET /api/usage 反映隱藏。"""
    client, settings = _usage_client(tmp_path, monkeypatch)
    # First verify claude is present
    r = client.get("/api/usage?include_hidden=1")
    sections = r.get_json()["sections"]
    claude_sec = [s for s in sections if s["key"] == "claude"]
    assert len(claude_sec) == 1
    # Now PATCH usage_hidden=["claude"]
    r2 = client.patch("/api/prefs", json={"usage_hidden": ["claude"]})
    assert r2.status_code == 200
    # GET without include_hidden -> claude filtered out
    r3 = client.get("/api/usage")
    sections = r3.get_json()["sections"]
    assert "claude" not in [s["key"] for s in sections]
    # GET with include_hidden=1 -> claude present and hidden=True
    r4 = client.get("/api/usage?include_hidden=1")
    sections = r4.get_json()["sections"]
    claude_sec = [s for s in sections if s["key"] == "claude"]
    assert len(claude_sec) == 1
    assert claude_sec[0]["hidden"] is True
    # Restore
    client.patch("/api/prefs", json={"usage_hidden": []})
