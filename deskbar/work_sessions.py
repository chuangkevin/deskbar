"""Display-safe work-session snapshots and one-time App-focus actions.

The Pi never learns a native Codex/Claude session id, a full path, or a shell
command.  Those private details stay in the Mac collector.  ``open_id`` is an
opaque, Mac-minted capability that only has meaning while that collector is
running.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Source = Literal["codex", "claude"]
ActivityState = Literal["result", "working", "waiting", "unknown"]
MAX_ACTIVE_AGE_SECONDS = 30 * 60
MAX_ACTIVE_SESSIONS = 6
ACTION_TTL_SECONDS = 60.0
_SOURCES = frozenset({"codex", "claude"})
_VALID_ACTIVITY_STATES = frozenset({"result", "working", "waiting", "unknown"})
_SENSITIVE_KEYS = frozenset({
    "prompt", "response", "lastPrompt", "customTitle", "token", "cookie",
    "cwd", "session_id", "sessionId", "session_uuid", "title",
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def safe_project_label(value: object) -> str:
    """Keep only a short display label; callers must pass a basename already."""
    if not isinstance(value, str):
        return "未命名專案"
    cleaned = " ".join(value.replace("\\", "/").split()).split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."}:
        return "未命名專案"
    return cleaned[:80]


@dataclass(frozen=True)
class WorkSessionItem:
    source: Source
    label: str
    last_active_at: datetime
    open_id: str
    activity_state: ActivityState = "unknown"
    project_label: str = "未命名專案"

    def is_active(self, now: datetime, cutoff_seconds: float = MAX_ACTIVE_AGE_SECONDS) -> bool:
        instant = self.last_active_at.astimezone(timezone.utc)
        age = (now.astimezone(timezone.utc) - instant).total_seconds()
        return 0 <= age < cutoff_seconds


@dataclass(frozen=True)
class WorkSessionError:
    source: Source
    code: Literal["unavailable", "permission", "corrupt", "unsupported"]


@dataclass(frozen=True)
class WorkSessionSnapshot:
    items: tuple[WorkSessionItem, ...] = ()
    errors: tuple[WorkSessionError, ...] = ()
    fetched_at: datetime = field(default_factory=utc_now)
    unseen_keys: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def active_items(self, now: datetime) -> tuple[WorkSessionItem, ...]:
        active = (item for item in self.items if item.is_active(now))
        return tuple(sorted(
            active,
            key=lambda item: (-item.last_active_at.timestamp(), item.source, item.open_id),
        )[:MAX_ACTIVE_SESSIONS])

    def item_for_open_id(self, open_id: str, now: datetime) -> WorkSessionItem | None:
        return next((item for item in self.active_items(now) if item.open_id == open_id), None)

    def unread_items(self, now: datetime) -> tuple[WorkSessionItem, ...]:
        active = self.active_items(now)
        return tuple(item for item in active if (item.source, item.open_id) in self.unseen_keys)

    def unread_count(self, now: datetime) -> int:
        return len(self.unread_items(now))

    def unread_result_items(self, now: datetime) -> tuple[WorkSessionItem, ...]:
        return tuple(item for item in self.unread_items(now) if item.activity_state == "result")

    def unread_result_count(self, now: datetime) -> int:
        return len(self.unread_result_items(now))

    def is_item_unread(self, item: WorkSessionItem, now: datetime) -> bool:
        return item.is_active(now) and (item.source, item.open_id) in self.unseen_keys


@dataclass(frozen=True)
class WorkSessionAction:
    action_id: str
    open_id: str
    source: Source
    expires_at: float

    def to_wire(self) -> dict[str, str]:
        return {"action_id": self.action_id, "open_id": self.open_id, "source": self.source}


class WorkSessionActionQueue:
    """Thread-safe, in-memory queue. Actions are intentionally one-time/short lived."""

    def __init__(self, ttl_seconds: float = ACTION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._actions: dict[str, WorkSessionAction] = {}
        self._lock = threading.Lock()

    def enqueue(self, *, open_id: str, source: Source, now_mono: float | None = None) -> str:
        now = time.monotonic() if now_mono is None else now_mono
        action = WorkSessionAction(secrets.token_urlsafe(18), open_id, source, now + self._ttl_seconds)
        with self._lock:
            self._purge(now)
            self._actions[action.action_id] = action
        return action.action_id

    def poll(self, now_mono: float | None = None) -> list[dict[str, str]]:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            self._purge(now)
            return [self._actions[action_id].to_wire() for action_id in sorted(self._actions)]

    def ack(self, action_id: str) -> bool:
        with self._lock:
            return self._actions.pop(action_id, None) is not None

    def _purge(self, now: float) -> None:
        for action_id, action in tuple(self._actions.items()):
            if action.expires_at <= now:
                self._actions.pop(action_id, None)


def snapshot_from_payload(payload: object, *, now: datetime | None = None) -> WorkSessionSnapshot:
    """Validate a display-safe collector payload at the Pi trust seam."""
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise ValueError("items must be a list")
    raw_errors = payload.get("errors", [])
    if not isinstance(raw_errors, list):
        raise ValueError("errors must be a list")

    parsed_items: list[WorkSessionItem] = []
    seen_open_ids: set[str] = set()
    for raw in items_value:
        if not isinstance(raw, dict):
            raise ValueError("session item must be a JSON object")
        if _SENSITIVE_KEYS.intersection(raw):
            raise ValueError("payload contains sensitive field")
        source = raw.get("source")
        open_id = raw.get("open_id")
        stamp = parse_timestamp(raw.get("last_active_at"))
        activity_state = raw.get("activity_state", "unknown")
        if activity_state is None:
            activity_state = "unknown"
        if not isinstance(activity_state, str) or activity_state not in _VALID_ACTIVITY_STATES:
            raise ValueError("invalid activity_state")
        if source not in _SOURCES:
            raise ValueError("invalid source")
        if not isinstance(open_id, str) or not (12 <= len(open_id) <= 160) or not open_id.isascii() or not open_id.isprintable():
            raise ValueError("invalid open_id")
        if open_id in seen_open_ids:
            raise ValueError("duplicate open_id")
        if stamp is None:
            raise ValueError("invalid last_active_at")
        raw_label = raw.get("label")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError("invalid label")
        cleaned_label = " ".join(raw_label.split()).strip()
        if "/" in cleaned_label or "\\" in cleaned_label:
            cleaned_label = cleaned_label.replace("\\", "/").split("/")[-1].strip()
        label = cleaned_label[:80] or "未命名 Session"

        if "project_label" in raw:
            project_label = safe_project_label(raw.get("project_label"))
        else:
            project_label = safe_project_label(raw.get("label"))

        seen_open_ids.add(open_id)
        parsed_items.append(WorkSessionItem(source, label, stamp, open_id, activity_state=activity_state, project_label=project_label))

    parsed_errors: list[WorkSessionError] = []
    for raw in raw_errors:
        if not isinstance(raw, dict) or set(raw) - {"source", "code"}:
            raise ValueError("invalid source error")
        source, code = raw.get("source"), raw.get("code")
        if source not in _SOURCES or code not in {"unavailable", "permission", "corrupt", "unsupported"}:
            raise ValueError("invalid source error")
        parsed_errors.append(WorkSessionError(source, code))

    fetched_at = parse_timestamp(payload.get("fetched_at")) or (now or utc_now())
    snapshot = WorkSessionSnapshot(tuple(parsed_items), tuple(parsed_errors), fetched_at)
    # Keep stale pushed items out of Pi state immediately as well as at render time.
    instant = now or utc_now()
    return WorkSessionSnapshot(snapshot.active_items(instant), snapshot.errors, snapshot.fetched_at)
