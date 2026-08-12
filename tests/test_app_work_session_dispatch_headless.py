import threading
from datetime import datetime, timedelta, timezone

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import Hit
from deskbar.ui.app import App
from deskbar.layout import Rect
from deskbar.work_sessions import WorkSessionItem, WorkSessionSnapshot


def test_dashboard_and_item_actions_only_enqueue_current_opaque_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    now = datetime.now(timezone.utc)
    item = WorkSessionItem("codex", "deskbar", now - timedelta(minutes=1), "opaque-open-id-123")
    state.set_work_sessions(WorkSessionSnapshot((item,)))
    app = App(state, Settings(), threading.Lock(), on_save=lambda _: None)
    app.hits = [Hit(Rect(0, 0, 10, 10), "open_work_sessions", None)]
    app._dispatch(1, 1)
    assert app.settings.center_view == "sessions"

    app.hits = [Hit(Rect(0, 0, 10, 10), "enqueue_work_session_action", item.open_id)]
    app._dispatch(1, 1)
    actions = state.poll_work_session_actions()
    assert len(actions) == 1 and actions[0]["source"] == "codex"

    app.hits = [Hit(Rect(0, 0, 10, 10), "enqueue_work_session_action", "forged-open-id")]
    app._dispatch(1, 1)
    assert len(state.poll_work_session_actions()) == 1

    app.hits = [Hit(Rect(0, 0, 10, 10), "enqueue_claude_dispatch", None)]
    app._dispatch(1, 1)
    assert any(action.get("kind") == "claude_dispatch" for action in state.poll_work_session_actions())


def test_toggle_center_entering_sessions_marks_sessions_as_seen(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    now = datetime.now(timezone.utc)
    item = WorkSessionItem("codex", "deskbar", now - timedelta(minutes=5), "open-id-1")
    state.set_work_sessions(WorkSessionSnapshot((item,)), now=now)

    # Updated session -> unread
    item_upd = WorkSessionItem("codex", "deskbar", now - timedelta(minutes=1), "open-id-1")
    state.set_work_sessions(WorkSessionSnapshot((item_upd,)), now=now)
    assert state.snapshot().work_sessions.unread_count(now) == 1

    settings = Settings()
    settings.center_view = "notes"
    app = App(state, settings, threading.Lock(), on_save=lambda _: None)

    app.hits = [Hit(Rect(0, 0, 10, 10), "toggle_center", None)]
    app._dispatch(1, 1)

    # Next view after notes in cycle is sessions
    assert app.settings.center_view == "sessions"
    assert state.snapshot().work_sessions.unread_count(now) == 0
