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

    snapshot = snapshot_from_payload(_payload(label="/private/project"), now=NOW)
    assert snapshot.items[0].label == "project"


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
