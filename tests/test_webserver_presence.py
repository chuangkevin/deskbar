"""POST /api/presence：外部主動推送在場狀態的端點測試。
501 / 401 (token 不符) / 400 (body 非 dict、present 缺、present 非 bool、rssi 非 int)
/ 204 happy path 且 store.set_presence 真的被寫入 / present=false 時不更新 last_seen。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from deskbar.alarms import AlarmStore
from deskbar.presence import PresenceState
from deskbar.store import AppState
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")


@pytest.fixture
def alarm_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    return store


def test_post_presence_store_none_returns_501():
    client = create_app(None).test_client()
    r = client.post("/api/presence", json={"present": True})
    assert r.status_code == 501


def test_post_presence_token_auth(alarm_store, monkeypatch):
    monkeypatch.setenv("DESKBAR_PUSH_TOKEN", "secret_token_123")
    app_state = AppState()
    client = create_app(alarm_store, usage_state=app_state).test_client()

    # 沒帶 header -> 401
    assert client.post("/api/presence", json={"present": True}).status_code == 401
    # 帶錯 header -> 401
    assert client.post("/api/presence", json={"present": True},
                        headers={"X-Deskbar-Token": "wrong"}).status_code == 401
    # 帶對 header -> 204
    r = client.post("/api/presence", json={"present": True},
                    headers={"X-Deskbar-Token": "secret_token_123"})
    assert r.status_code == 204


def test_post_presence_bad_body_returns_400(alarm_store):
    client = create_app(alarm_store, usage_state=AppState()).test_client()

    # 非 dict body
    assert client.post("/api/presence", json=[1, 2, 3]).status_code == 400
    assert client.post("/api/presence", json="string").status_code == 400

    # 缺 present
    assert client.post("/api/presence", json={"rssi": -50}).status_code == 400

    # present 非 bool
    assert client.post("/api/presence", json={"present": "true"}).status_code == 400
    assert client.post("/api/presence", json={"present": 1}).status_code == 400

    # rssi 非 int (bool 或 string)
    assert client.post("/api/presence", json={"present": True, "rssi": True}).status_code == 400
    assert client.post("/api/presence", json={"present": True, "rssi": "-50"}).status_code == 400


def test_post_presence_happy_path_204_and_updates_store(alarm_store):
    app_state = AppState()
    client = create_app(alarm_store, usage_state=app_state).test_client()

    r = client.post("/api/presence", json={"present": True, "rssi": -65})
    assert r.status_code == 204
    assert r.get_data() == b""

    st = app_state.snapshot().presence
    assert st.present is True
    assert st.rssi == -65
    assert isinstance(st.last_seen, datetime)


def test_post_presence_false_does_not_update_last_seen(alarm_store):
    app_state = AppState()
    old_last_seen = datetime(2026, 8, 4, 10, 0, tzinfo=TZ)
    app_state.set_presence(PresenceState(present=True, rssi=-55,
                                         last_seen=old_last_seen, enabled=True))

    client = create_app(alarm_store, usage_state=app_state).test_client()
    r = client.post("/api/presence", json={"present": False})
    assert r.status_code == 204

    st = app_state.snapshot().presence
    assert st.present is False
    assert st.last_seen == old_last_seen
