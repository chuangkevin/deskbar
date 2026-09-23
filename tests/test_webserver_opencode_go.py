"""OpenCode Go 端對端：POST /api/usage（含 og_accounts）→ GET /api/usage 看得到
key 為 opencode:<id> 的區塊、三條 bar（5H／本週／本月）、billing 自動付款日。

以及補充規格驗收：沒有 key 檔 → 沒有 opencode 區塊；
兩把 key → 兩個 opencode:* 區塊。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from deskbar.alarms import AlarmStore
from deskbar.claudeusage import OgAccount
from deskbar.store import AppState
from deskbar.ui import usagewidget
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 9, 23, 16, 0, tzinfo=TZ)

VALID_PAYLOAD = {
    "session_pct": 42.0, "session_resets_at": "2026-07-27T18:00:00Z",
    "weekly_pct": 61.5, "weekly_resets_at": "2026-08-02T00:00:00+00:00",
}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    state = AppState()
    return create_app(store, usage_state=state).test_client(), state


def _og_payload():
    now = datetime.now(TZ)
    return dict(
        VALID_PAYLOAD,
        og_fetched_at=now.isoformat(),
        og_accounts=[{
            "account_id": "abc123def456",
            "name": "",
            "five_hour_pct": 0.0,
            "five_hour_resets_at": "2026-09-23T10:39:45.011Z",
            "weekly_pct": 75.0,
            "weekly_resets_at": "2026-09-28T00:00:00.000Z",
            "monthly_pct": 100.0,
            "monthly_resets_at": "2026-10-11T02:09:57.000Z",
            "billing_at": "2026-10-11T02:09:57.000Z",
            "fetched_at": now.isoformat(),
        }],
    )


def test_post_og_accounts_to_get_usage_roundtrip(tmp_path, monkeypatch):
    """驗收線 2：POST 含 og_* 的 payload → GET 看得到 opencode 區塊、三條 bar。"""
    client, state = _client(tmp_path, monkeypatch)
    assert client.post("/api/usage", json=_og_payload()).status_code == 204

    r = client.get("/api/usage")
    assert r.status_code == 200
    sections = r.get_json()["sections"]
    og_sections = [s for s in sections if s["key"] == "opencode:abc123def456"]
    assert len(og_sections) == 1
    section = og_sections[0]
    assert section["title"] == "OPENCODE GO"
    assert [g["label"] for g in section["groups"]] == ["5H", "本週", "本月"]
    by_label = {g["label"]: g for g in section["groups"]}
    assert by_label["5H"]["pct"] == 0.0
    assert by_label["本週"]["pct"] == 75.0
    assert by_label["本月"]["pct"] == 100.0
    # monthly resetsAt 當自動付款日
    assert section["billing_at"] == "2026-10-11"
    assert section["billing_source"] == "auto"
    assert section["billing_days"] == (datetime(2026, 10, 11).date() - datetime.now(TZ).date()).days


def test_no_og_accounts_means_no_opencode_section(tmp_path, monkeypatch):
    """補充驗收：沒有 key（不送 og_accounts）→ /api/usage 沒有 opencode 區塊。"""
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/api/usage", json=dict(VALID_PAYLOAD)).status_code == 204
    r = client.get("/api/usage")
    assert r.status_code == 200
    keys = [s["key"] for s in r.get_json()["sections"]]
    assert not any(k == "opencode" or k.startswith("opencode:") for k in keys)


def test_two_keys_give_two_opencode_sections(tmp_path, monkeypatch):
    """補充驗收：兩把 key → 兩個 opencode:* 區塊，第二張標題 OPENCODE GO · 2。"""
    client, _ = _client(tmp_path, monkeypatch)
    now = datetime.now(TZ)
    payload = dict(VALID_PAYLOAD, og_fetched_at=now.isoformat(), og_accounts=[
        {"account_id": "id-one-111111", "five_hour_pct": 1.0,
         "five_hour_resets_at": now.isoformat(), "weekly_pct": 10.0,
         "weekly_resets_at": now.isoformat(), "monthly_pct": 20.0,
         "monthly_resets_at": now.isoformat(), "billing_at": now.isoformat(),
         "fetched_at": now.isoformat()},
        {"account_id": "id-two-222222", "five_hour_pct": 2.0,
         "five_hour_resets_at": now.isoformat(), "weekly_pct": 30.0,
         "weekly_resets_at": now.isoformat(), "monthly_pct": 40.0,
         "monthly_resets_at": now.isoformat(), "billing_at": now.isoformat(),
         "fetched_at": now.isoformat()},
    ])
    assert client.post("/api/usage", json=payload).status_code == 204
    r = client.get("/api/usage")
    assert r.status_code == 200
    sections = r.get_json()["sections"]
    og_sections = [s for s in sections if s["key"].startswith("opencode:")]
    assert [s["key"] for s in og_sections] == ["opencode:id-one-111111", "opencode:id-two-222222"]
    assert [s["title"] for s in og_sections] == ["OPENCODE GO", "OPENCODE GO · 2"]


def test_og_section_hidden_when_source_disabled():
    """opencode 開關關掉 → 右欄不畫這一區（即使有資料）。"""
    usage = usagewidget_visible_usage()
    titles = [t for t, _g, _a, _k in usagewidget.visible_sections(
        usage, NOW, ("claude", "antigravity", "openai", "cursor", "commandcode"))]
    assert not any(t.startswith("OPENCODE GO") for t in titles)
    titles = [t for t, _g, _a, _k in usagewidget.visible_sections(
        usage, NOW, ("claude", "antigravity", "openai", "cursor", "commandcode", "opencode"))]
    assert "OPENCODE GO" in titles


def usagewidget_visible_usage():
    from dataclasses import replace
    from deskbar.claudeusage import UsageInfo
    return replace(
        UsageInfo(session_pct=1.0, session_resets_at=NOW + timedelta(hours=1),
                  weekly_pct=1.0, weekly_resets_at=NOW + timedelta(days=1),
                  fable_pct=None, fable_resets_at=None, fetched_at=NOW),
        og_accounts=(OgAccount("abc123", "", 0.0, NOW + timedelta(hours=5),
                               75.0, NOW + timedelta(days=5),
                               100.0, NOW + timedelta(days=18),
                               NOW + timedelta(days=18), NOW),),
    )


def test_og_pct_out_of_range_is_clamped(tmp_path, monkeypatch):
    """超額百分比壓回 0–100 照收，不整包 400。"""
    client, state = _client(tmp_path, monkeypatch)
    payload = _og_payload()
    payload["og_accounts"][0]["weekly_pct"] = 100.2155
    payload["og_accounts"][0]["five_hour_pct"] = -1
    payload["og_accounts"][0]["monthly_pct"] = 250
    assert client.post("/api/usage", json=payload).status_code == 204
    account = state.snapshot().usage.og_accounts[0]
    assert account.weekly_pct == 100.0
    assert account.five_hour_pct == 0.0
    assert account.monthly_pct == 100.0


def test_og_accounts_bad_type_still_400(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.post("/api/usage", json=dict(
        VALID_PAYLOAD, og_accounts=[{"account_id": "x", "weekly_pct": "42"}])).status_code == 400
    assert client.post("/api/usage", json=dict(
        VALID_PAYLOAD, og_accounts=[{"account_id": "x", "weekly_pct": True}])).status_code == 400
    assert client.post("/api/usage", json=dict(
        VALID_PAYLOAD, og_accounts="nope")).status_code == 400
