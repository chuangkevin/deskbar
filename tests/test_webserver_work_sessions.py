from datetime import datetime, timedelta, timezone

import pytest

from deskbar.alarms import AlarmStore
from deskbar.store import AppState
from deskbar.webserver import create_app

NOW = datetime.now(timezone.utc)


@pytest.fixture
def alarm_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    result = AlarmStore()
    result.load()
    return result


def _payload(**item):
    session = {"source": "codex", "label": "deskbar", "open_id": "opaque-open-id-123",
               "last_active_at": (NOW - timedelta(minutes=1)).isoformat()}
    session.update(item)
    return {"items": [session], "errors": [], "fetched_at": NOW.isoformat()}


def test_push_filters_and_queues_action(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    assert client.post("/api/work-sessions", json=_payload()).status_code == 204
    item = state.snapshot().work_sessions.items[0]
    action_id = state.enqueue_work_session_action(item.open_id)
    assert action_id
    actions = client.get("/api/work-sessions/actions").get_json()["actions"]
    assert actions == [{"action_id": action_id, "open_id": item.open_id, "source": "codex"}]
    assert client.post("/api/work-sessions/actions/ack", json={"action_id": action_id}).status_code == 204
    assert client.get("/api/work-sessions/actions").get_json()["actions"] == []


def test_successfully_opened_desktop_session_marks_only_that_item_seen(alarm_store):
    state = AppState()
    client = create_app(alarm_store, usage_state=state).test_client()
    assert client.post("/api/work-sessions", json=_payload(last_active_at=(NOW - timedelta(minutes=5)).isoformat())).status_code == 204
    assert client.post("/api/work-sessions", json=_payload(last_active_at=(NOW - timedelta(minutes=1)).isoformat())).status_code == 204
    item = state.snapshot().work_sessions.items[0]
    assert state.snapshot().work_sessions.is_item_unread(item, datetime.now(timezone.utc))

    action_id = state.enqueue_work_session_action(item.open_id)
    assert client.post("/api/work-sessions/actions/ack", json={"action_id": action_id, "opened": True}).status_code == 204

    assert not state.snapshot().work_sessions.is_item_unread(item, datetime.now(timezone.utc))
    assert client.post("/api/work-sessions/actions/ack", json={"action_id": "x", "opened": "yes"}).status_code == 400


def test_read_only_status_omits_action_capability(alarm_store):
    client = create_app(alarm_store, usage_state=AppState()).test_client()
    assert client.post("/api/work-sessions", json=_payload(activity_state="result", project_label="myproj")).status_code == 204

    body = client.get("/api/work-sessions").get_json()
    assert len(body["items"]) == 1
    assert body["items"][0]["source"] == "codex"
    assert body["items"][0]["label"] == "deskbar"
    assert body["items"][0]["project_label"] == "myproj"
    assert body["items"][0]["activity_state"] == "result"
    assert "open_id" not in body["items"][0]


def test_push_rejects_sensitive_or_invalid_payload_and_stale_session(alarm_store):
    client = create_app(alarm_store, usage_state=AppState()).test_client()
    assert client.post("/api/work-sessions", json=_payload(prompt="do not leak")).status_code == 400
    assert client.post("/api/work-sessions", json={"items": "nope"}).status_code == 400
    stale = _payload(last_active_at=(NOW - timedelta(minutes=31)).isoformat())
    assert client.post("/api/work-sessions", json=stale).status_code == 204


def test_push_and_action_routes_require_token_when_enabled(alarm_store, monkeypatch):
    monkeypatch.setenv("DESKBAR_PUSH_TOKEN", "test-only-token")
    client = create_app(alarm_store, usage_state=AppState()).test_client()
    assert client.post("/api/work-sessions", json=_payload()).status_code == 401
    assert client.post("/api/work-sessions", json=_payload(), headers={"X-Deskbar-Token": "test-only-token"}).status_code == 204
    assert client.get("/api/work-sessions/actions").status_code == 401
    assert client.post("/api/work-sessions/actions/ack", json={"action_id": "x"}).status_code == 401


def test_routes_return_501_without_state(alarm_store):
    client = create_app(alarm_store).test_client()
    assert client.post("/api/work-sessions", json=_payload()).status_code == 501
    assert client.get("/api/work-sessions").status_code == 501
    assert client.get("/api/work-sessions/actions").status_code == 501
