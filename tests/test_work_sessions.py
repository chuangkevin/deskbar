from datetime import datetime, timedelta, timezone

import pytest

from deskbar.work_sessions import (
    ACTION_TTL_SECONDS,
    MAX_ACTIVE_SESSIONS,
    WorkSessionActionQueue,
    WorkSessionItem,
    WorkSessionSnapshot,
    snapshot_from_payload,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _item(source="codex", minutes=1, open_id="opaque-open-id-123"):
    return WorkSessionItem(source, "deskbar", NOW - timedelta(minutes=minutes), open_id)


def _payload(**item):
    base = {"source": "codex", "label": "deskbar", "last_active_at": (NOW - timedelta(minutes=1)).isoformat(),
            "open_id": "opaque-open-id-123"}
    base.update(item)
    return {"items": [base], "errors": [], "fetched_at": NOW.isoformat()}


@pytest.mark.parametrize("minutes,expected", [(29, True), (30, False), (31, False)])
def test_activity_cutoff_is_strictly_less_than_thirty_minutes(minutes, expected):
    assert _item(minutes=minutes).is_active(NOW) is expected


def test_snapshot_sorts_latest_first_then_source_and_opaque_id():
    snapshot = WorkSessionSnapshot((
        _item("claude", 3, "z" * 12),
        _item("codex", 1, "b" * 12),
        _item("claude", 1, "a" * 12),
    ))
    assert [item.open_id for item in snapshot.active_items(NOW)] == ["a" * 12, "b" * 12, "z" * 12]


def test_only_the_six_most_recent_active_sessions_are_exposed():
    items = tuple(
        _item(minutes=index, open_id=f"opaque-open-id-{index:02d}")
        for index in range(MAX_ACTIVE_SESSIONS + 2)
    )
    snapshot = WorkSessionSnapshot(items)
    assert [item.open_id for item in snapshot.active_items(NOW)] == [
        f"opaque-open-id-{index:02d}" for index in range(MAX_ACTIVE_SESSIONS)
    ]


def test_payload_rejects_sensitive_fields_and_normalizes_path_to_basename():
    unsafe = _payload(cwd="/private/project")
    with pytest.raises(ValueError, match="sensitive"):
        snapshot_from_payload(unsafe, now=NOW)

    unsafe_title = _payload(title="raw sensitive key in payload")
    with pytest.raises(ValueError, match="sensitive"):
        snapshot_from_payload(unsafe_title, now=NOW)

    snapshot = snapshot_from_payload(_payload(label="/private/project", project_label="/private/project"), now=NOW)
    assert snapshot.items[0].label == "project"
    assert snapshot.items[0].project_label == "project"

    dispatch = snapshot_from_payload(_payload(progress_label="2/4 完成 · 進行中"), now=NOW)
    assert dispatch.items[0].progress_label == "2/4 完成 · 進行中"

    with pytest.raises(ValueError, match="progress_label"):
        snapshot_from_payload(_payload(progress_label=2), now=NOW)


def test_stale_payload_is_removed_before_store_and_valid_open_id_can_resolve():
    data = _payload(last_active_at=(NOW - timedelta(minutes=31)).isoformat())
    assert snapshot_from_payload(data, now=NOW).items == ()

    snapshot = WorkSessionSnapshot((_item(),))
    assert snapshot.item_for_open_id("opaque-open-id-123", NOW) is not None
    assert snapshot.item_for_open_id("not-known-token", NOW) is None


def test_action_queue_ack_and_ttl_are_one_time():
    queue = WorkSessionActionQueue()
    action_id = queue.enqueue(open_id="opaque-open-id-123", source="codex", now_mono=10.0)
    assert queue.poll(now_mono=10.0) == [{"action_id": action_id, "open_id": "opaque-open-id-123", "source": "codex"}]
    assert queue.ack(action_id) is True
    assert queue.ack(action_id) is False

    queue.enqueue(open_id="another-opaque-123", source="claude", now_mono=10.0)
    assert queue.poll(now_mono=10.0 + ACTION_TTL_SECONDS) == []


def test_claude_dispatch_action_is_explicit_and_has_no_session_capability():
    queue = WorkSessionActionQueue()
    action_id = queue.enqueue_claude_dispatch(now_mono=10.0)
    assert queue.poll(now_mono=10.0) == [{
        "action_id": action_id,
        "source": "claude",
        "kind": "claude_dispatch",
    }]


def test_store_enqueues_fixed_dispatch_without_a_session_capability():
    from deskbar.store import AppState

    state = AppState()
    state.set_work_sessions(WorkSessionSnapshot((_item("codex"),)))
    assert state.enqueue_claude_dispatch_action()
    assert state.poll_work_session_actions()[0].get("open_id") is None


def test_initial_baseline_does_not_mark_old_sessions_as_unread():
    from deskbar.store import AppState
    state = AppState()
    item1 = _item("codex", 5, "open-111111111111")
    item2 = _item("claude", 10, "open-222222222222")

    state.set_work_sessions(WorkSessionSnapshot((item1, item2)), now=NOW)
    snap = state.snapshot()

    assert snap.work_sessions.unread_count(NOW) == 0
    assert snap.work_sessions.unread_items(NOW) == ()
    assert not snap.work_sessions.is_item_unread(item1, NOW)


def test_same_session_update_and_new_session_trigger_unread_attention():
    from deskbar.store import AppState
    state = AppState()
    item1 = _item("codex", 5, "open-111111111111")

    # Initial baseline
    state.set_work_sessions(WorkSessionSnapshot((item1,)), now=NOW)
    assert state.snapshot().work_sessions.unread_count(NOW) == 0

    # Same session updated with newer timestamp
    item1_updated = WorkSessionItem("codex", "deskbar", NOW - timedelta(minutes=1), "open-111111111111")
    state.set_work_sessions(WorkSessionSnapshot((item1_updated,)), now=NOW)
    snap = state.snapshot()

    assert snap.work_sessions.unread_count(NOW) == 1
    assert snap.work_sessions.is_item_unread(item1_updated, NOW)

    # New session arrives
    item2 = _item("claude", 2, "open-222222222222")
    state.set_work_sessions(WorkSessionSnapshot((item1_updated, item2)), now=NOW)
    snap2 = state.snapshot()

    assert snap2.work_sessions.unread_count(NOW) == 2


def test_mark_work_sessions_seen_clears_unread_status():
    from deskbar.store import AppState
    state = AppState()
    item1 = _item("codex", 5, "open-111111111111")
    state.set_work_sessions(WorkSessionSnapshot((item1,)), now=NOW)

    item1_updated = WorkSessionItem("codex", "deskbar", NOW - timedelta(minutes=1), "open-111111111111")
    state.set_work_sessions(WorkSessionSnapshot((item1_updated,)), now=NOW)
    assert state.snapshot().work_sessions.unread_count(NOW) == 1

    state.mark_work_sessions_seen(now=NOW)
    assert state.snapshot().work_sessions.unread_count(NOW) == 0


def test_activity_state_validation_and_backward_compatibility():
    # Missing activity_state -> defaults to "unknown"
    snap = snapshot_from_payload(_payload(), now=NOW)
    assert snap.items[0].activity_state == "unknown"

    # Valid activity_state -> accepted
    snap_result = snapshot_from_payload(_payload(activity_state="result"), now=NOW)
    assert snap_result.items[0].activity_state == "result"

    # Invalid activity_state -> raises ValueError
    with pytest.raises(ValueError, match="invalid activity_state"):
        snapshot_from_payload(_payload(activity_state="illegal_state"), now=NOW)
    with pytest.raises(ValueError, match="invalid activity_state"):
        snapshot_from_payload(_payload(activity_state=[]), now=NOW)


def test_unread_result_count_and_items():
    from deskbar.store import AppState
    state = AppState()
    item_res = WorkSessionItem("codex", "proj-a", NOW - timedelta(minutes=10), "open-111111111111", activity_state="result")
    item_work = WorkSessionItem("claude", "proj-b", NOW - timedelta(minutes=10), "open-222222222222", activity_state="working")

    # Baseline
    state.set_work_sessions(WorkSessionSnapshot((item_res, item_work)), now=NOW)
    assert state.snapshot().work_sessions.unread_result_count(NOW) == 0

    # Updates -> trigger unseen
    item_res_upd = WorkSessionItem("codex", "proj-a", NOW - timedelta(minutes=1), "open-111111111111", activity_state="result")
    item_work_upd = WorkSessionItem("claude", "proj-b", NOW - timedelta(minutes=1), "open-222222222222", activity_state="working")
    state.set_work_sessions(WorkSessionSnapshot((item_res_upd, item_work_upd)), now=NOW)

    snap = state.snapshot()
    assert snap.work_sessions.unread_count(NOW) == 2
    assert snap.work_sessions.unread_result_count(NOW) == 1
    assert [item.label for item in snap.work_sessions.unread_result_items(NOW)] == ["proj-a"]
