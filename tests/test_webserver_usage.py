"""POST /api/usage：Mac agent 推送 usage 的被動接收端點。成功寫入 state 並回
204；各種格式錯誤回 400；沒接 usage_state 回 501；DESKBAR_PUSH_TOKEN 有設定時
沒帶對的 X-Deskbar-Token 回 401，帶對了照常放行。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from deskbar.alarms import AlarmStore
from deskbar.store import AppState
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")

VALID_PAYLOAD = {
    "session_pct": 42.0, "session_resets_at": "2026-07-27T18:00:00Z",
    "weekly_pct": 61.5, "weekly_resets_at": "2026-08-02T00:00:00+00:00",
    "fable_pct": 12.0, "fable_resets_at": "2026-08-02T00:00:00Z",
}


@pytest.fixture
def alarm_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    return store


# ---------------------------------------------------------------- 成功路徑


def test_post_usage_returns_204_and_writes_state(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    r = client.post("/api/usage", json=VALID_PAYLOAD)
    assert r.status_code == 204
    assert r.get_data() == b""

    usage = state.snapshot().usage
    assert usage is not None
    assert usage.session_pct == 42.0
    assert usage.weekly_pct == 61.5
    assert usage.fable_pct == 12.0
    assert usage.session_resets_at is not None
    assert usage.weekly_resets_at is not None
    assert usage.fable_resets_at is not None
    assert isinstance(usage.fetched_at, datetime)
    # 向後相容：未帶 AG 欄位時預設為 None
    assert usage.ag_5h_pct is None
    assert usage.ag_5h_resets_at is None
    assert usage.ag_weekly_pct is None
    assert usage.ag_weekly_resets_at is None
    assert usage.oa_weekly_pct is None
    assert usage.oa_weekly_resets_at is None


def test_post_usage_with_antigravity_fields_success(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    payload = dict(VALID_PAYLOAD,
                   ag_5h_pct=35.76, ag_5h_resets_at="2026-08-04T18:00:00Z",
                   ag_weekly_pct=5.96, ag_weekly_resets_at="2026-08-11T00:00:00Z")
    r = client.post("/api/usage", json=payload)
    assert r.status_code == 204
    usage = state.snapshot().usage
    assert usage.ag_5h_pct == 35.76
    assert usage.ag_weekly_pct == 5.96
    assert usage.ag_5h_resets_at is not None
    assert usage.ag_weekly_resets_at is not None


def test_post_usage_with_openai_fields_success(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    payload = dict(VALID_PAYLOAD,
                   oa_weekly_pct=3.0, oa_weekly_resets_at="2026-08-17T00:00:00Z")
    r = client.post("/api/usage", json=payload)
    assert r.status_code == 204
    usage = state.snapshot().usage
    assert usage.oa_weekly_pct == 3.0
    assert usage.oa_weekly_resets_at is not None


def test_post_usage_without_openai_fields_still_returns_204(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    r = client.post("/api/usage", json=VALID_PAYLOAD)
    assert r.status_code == 204
    usage = state.snapshot().usage
    assert usage.oa_weekly_pct is None
    assert usage.oa_weekly_resets_at is None


def test_post_usage_allows_all_null_fields(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    payload = {"session_pct": None, "session_resets_at": None,
              "weekly_pct": None, "weekly_resets_at": None,
              "fable_pct": None, "fable_resets_at": None,
              "ag_5h_pct": None, "ag_5h_resets_at": None,
              "ag_weekly_pct": None, "ag_weekly_resets_at": None,
              "oa_weekly_pct": None, "oa_weekly_resets_at": None}
    r = client.post("/api/usage", json=payload)
    assert r.status_code == 204
    usage = state.snapshot().usage
    assert usage.session_pct is None
    assert usage.fable_resets_at is None
    assert usage.ag_5h_pct is None
    assert usage.ag_weekly_pct is None
    assert usage.oa_weekly_pct is None


def test_post_usage_preserves_cached_fetched_at(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, fetched_at="2026-08-04T01:23:45+00:00")

    assert client.post("/api/usage", json=payload).status_code == 204
    assert state.snapshot().usage.fetched_at == datetime.fromisoformat(
        "2026-08-04T01:23:45+00:00"
    )


def test_post_usage_rejects_invalid_fetched_at(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, fetched_at="yesterday-ish")

    assert client.post("/api/usage", json=payload).status_code == 400


def test_post_usage_pct_boundaries_zero_and_hundred_are_valid(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    payload = dict(VALID_PAYLOAD, session_pct=0, weekly_pct=100)
    r = client.post("/api/usage", json=payload)
    assert r.status_code == 204
    usage = state.snapshot().usage
    assert usage.session_pct == 0.0
    assert usage.weekly_pct == 100.0


# ---------------------------------------------------------------- 400：格式錯誤


def test_post_usage_non_dict_body_returns_400(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    assert client.post("/api/usage", json=[1, 2, 3]).status_code == 400
    assert client.post("/api/usage", json="oops").status_code == 400
    assert client.post("/api/usage", data="not json",
                       content_type="text/plain").status_code == 400


@pytest.mark.parametrize("field", ["session_pct", "weekly_pct", "fable_pct", "ag_5h_pct", "ag_weekly_pct", "oa_weekly_pct"])
def test_post_usage_pct_not_a_number_returns_400(alarm_store, field):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, **{field: "42"})
    assert client.post("/api/usage", json=payload).status_code == 400


@pytest.mark.parametrize("field", ["session_pct", "weekly_pct", "fable_pct", "ag_5h_pct", "ag_weekly_pct", "oa_weekly_pct"])
def test_post_usage_pct_bool_returns_400(alarm_store, field):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, **{field: True})
    assert client.post("/api/usage", json=payload).status_code == 400


@pytest.mark.parametrize("field,value", [
    ("session_pct", -1), ("weekly_pct", 101), ("fable_pct", 1000),
    ("ag_5h_pct", -0.1), ("ag_weekly_pct", 100.1),
    ("oa_weekly_pct", 101),
])
def test_post_usage_pct_out_of_range_returns_400(alarm_store, field, value):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, **{field: value})
    assert client.post("/api/usage", json=payload).status_code == 400


@pytest.mark.parametrize("field", [
    "session_resets_at", "weekly_resets_at", "fable_resets_at",
    "ag_5h_resets_at", "ag_weekly_resets_at", "oa_weekly_resets_at",
])
def test_post_usage_unparseable_resets_at_returns_400(alarm_store, field):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, **{field: "not-a-date"})
    assert client.post("/api/usage", json=payload).status_code == 400


@pytest.mark.parametrize("field", [
    "session_resets_at", "weekly_resets_at", "fable_resets_at",
    "ag_5h_resets_at", "ag_weekly_resets_at", "oa_weekly_resets_at",
])
def test_post_usage_resets_at_wrong_type_returns_400(alarm_store, field):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    payload = dict(VALID_PAYLOAD, **{field: 12345})
    assert client.post("/api/usage", json=payload).status_code == 400


# ---------------------------------------------------------------- 501：未接 state


def test_post_usage_without_usage_state_returns_501(alarm_store):
    client = create_app(alarm_store).test_client()
    r = client.post("/api/usage", json=VALID_PAYLOAD)
    assert r.status_code == 501


# ---------------------------------------------------------------- DESKBAR_PUSH_TOKEN 保護


def test_post_usage_requires_token_header_when_env_set(alarm_store, monkeypatch):
    monkeypatch.setenv("DESKBAR_PUSH_TOKEN", "secret123")
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()

    r = client.post("/api/usage", json=VALID_PAYLOAD)
    assert r.status_code == 401
    assert state.snapshot().usage is None

    r = client.post("/api/usage", json=VALID_PAYLOAD,
                    headers={"X-Deskbar-Token": "wrong"})
    assert r.status_code == 401

    r = client.post("/api/usage", json=VALID_PAYLOAD,
                    headers={"X-Deskbar-Token": "secret123"})
    assert r.status_code == 204
    assert state.snapshot().usage is not None


def test_post_usage_no_token_check_when_env_unset(alarm_store, monkeypatch):
    monkeypatch.delenv("DESKBAR_PUSH_TOKEN", raising=False)
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    r = client.post("/api/usage", json=VALID_PAYLOAD)
    assert r.status_code == 204
