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
    assert app.view == "work_sessions"

    app.hits = [Hit(Rect(0, 0, 10, 10), "enqueue_work_session_action", item.open_id)]
    app._dispatch(1, 1)
    actions = state.poll_work_session_actions()
    assert len(actions) == 1 and actions[0]["source"] == "codex"

    app.hits = [Hit(Rect(0, 0, 10, 10), "enqueue_work_session_action", "forged-open-id")]
    app._dispatch(1, 1)
    assert len(state.poll_work_session_actions()) == 1
