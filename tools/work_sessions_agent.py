#!/usr/bin/env python3
"""Mac-side collector for Deskbar's display-safe active-session panel.

It intentionally treats Codex and Claude files as private implementation
details. It reads only identifiers, timestamps, a cwd basename, and the
user-visible session title. Conversation text is never returned, logged, or
sent to the Pi.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import secrets
import select
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deskbar.work_sessions import (
    MAX_ACTIVE_AGE_SECONDS,
    MAX_ACTIVE_SESSIONS,
    parse_timestamp,
    safe_project_label,
)

DEFAULT_URL = "http://100.98.35.59:8080"
# This is the click-to-desktop control path.  Keep its worst-case queue wait
# below one second; session collection remains the lower-frequency operation.
POLL_SECONDS = 1.0
COLLECT_SECONDS = 15.0
APP_OPEN_ARGS = {
    # Bundle ID survives display-name changes and makes the target unambiguous.
    "codex": ("/usr/bin/open", "-b", "com.openai.codex"),
    "claude": ("/usr/bin/open", "-a", "Claude"),
}
_TAIL_BYTES = 128 * 1024
_CODEX_APP_SERVER = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
_CODEX_APP_SERVER_TIMEOUT_SECONDS = 6


def _current_user_home() -> Path:
    """Resolve the login user's home without trusting a blank LaunchAgent HOME."""
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return Path.home()


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


@dataclass(frozen=True)
class LocalSession:
    source: str
    native_id: str
    label: str
    project_label: str
    last_active_at: datetime
    activity_state: str = "unknown"
    progress_label: str = ""


@dataclass(frozen=True)
class OpenTarget:
    source: str
    native_id: str


@dataclass(frozen=True)
class SourceProblem:
    source: str
    code: str


@dataclass(frozen=True)
class CodexThreadDetails:
    """Only the display metadata required to match the Codex task list."""

    title: object
    cwd: object
    source: object = None
    thread_source: object = None
    name: object = None

    @property
    def is_internal_work_record(self) -> bool:
        """Internal exec/subagent threads are not selectable Codex tasks."""
        source = self.source.strip().lower() if isinstance(self.source, str) else ""
        thread_source = self.thread_source.strip().lower() if isinstance(self.thread_source, str) else ""
        return source == "exec" or thread_source == "subagent"

    @property
    def display_title(self) -> object:
        """``name`` is Codex's current task-list display name when available."""
        return self.name if _clean_label(self.name) else self.title


_WORKING_TYPES = frozenset({
    "reasoning", "thinking", "thought", "tool", "tool_use", "tool_call",
    "tool_result", "function_call", "function_call_output", "exec", "bash",
    "command", "agent_work", "turn_start", "agent_reasoning", "progress",
    "tool_execution", "custom_tool_call", "custom_tool_call_output",
    "mcp_tool_call", "mcp_tool_call_end",
})
_WAITING_TYPES = frozenset({"user", "user_message", "user_input", "human", "prompt", "input"})
_RESULT_TYPES = frozenset({
    "assistant", "assistant_message", "message", "response", "reply",
    "agent_message", "message_stop", "turn_end", "completion", "text",
})


_PRIVATE_ABSOLUTE_PATH_RE = re.compile(r"/(?:Users|private|Volumes|home)(?:/[^\s/]+)+")


def _clean_label(value: object, max_len: int = 80) -> str:
    """Clean a user-visible title without destroying it when it contains a path.

    Codex titles are sometimes generated from the first message and can include a
    project path between two meaningful phrases.  The old implementation split
    on every slash, turning such a title into its trailing fragment.  Redact only
    known absolute filesystem paths, while retaining the rest of the title.
    """
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return ""
    cleaned = _PRIVATE_ABSOLUTE_PATH_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_len]


def safe_session_labels(title_val: object, cwd_val: object, default_label: str = "未命名 Session") -> tuple[str, str]:
    project_label = safe_project_label(cwd_val)
    title = _clean_label(title_val)
    if title:
        label = title
    elif project_label and project_label != "未命名專案":
        label = project_label
    else:
        label = default_label
    return label, project_label


def _classify_event(value: dict) -> str:
    """Classify activity state using ONLY safe schema fields: type, payload.type, payload.role.
    Never inspect message text, content, summary, prompt, or output values.
    """
    if not isinstance(value, dict):
        return "unknown"

    top_type = value.get("type") if isinstance(value.get("type"), str) else ""
    payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    pay_type = payload.get("type") if isinstance(payload.get("type"), str) else ""
    pay_role = payload.get("role") if isinstance(payload.get("role"), str) else (
        value.get("role") if isinstance(value.get("role"), str) else ""
    )

    if pay_role in ("user", "human") or top_type in _WAITING_TYPES or pay_type in _WAITING_TYPES:
        return "waiting"

    if top_type in _WORKING_TYPES or pay_type in _WORKING_TYPES:
        return "working"

    if pay_role in ("assistant", "agent"):
        return "result"
    if top_type in _RESULT_TYPES or pay_type in _RESULT_TYPES:
        return "result"

    return "unknown"


def _json_lines(path: Path) -> tuple[dict | None, datetime | None, str]:
    """Read one metadata line and a bounded tail, never a whole transcript.

    Session files can contain hundreds of thousands of conversation events.
    File mtime remains a safe fallback when the final JSON record is larger than
    the bounded tail or malformed.
    """
    first: dict | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        line = handle.readline()
    if line.strip():
        try:
            value = json.loads(line)
            first = value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass

    tail_stamp: datetime | None = None
    activity_state: str = "unknown"
    tail_lines_checked = 0

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - _TAIL_BYTES))
        tail = handle.read()

    for raw_line in reversed(tail.splitlines()):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            tail_lines_checked += 1
            if tail_stamp is None:
                stamp = parse_timestamp(value.get("timestamp"))
                if stamp is not None:
                    tail_stamp = stamp
            if activity_state == "unknown":
                st = _classify_event(value)
                if st != "unknown":
                    activity_state = st
            if (tail_stamp is not None and activity_state != "unknown") or tail_lines_checked >= 3:
                break

    return first, tail_stamp, activity_state


def _best_time(*instants: datetime | str | None) -> datetime | None:
    usable: list[datetime] = []
    for instant in instants:
        if isinstance(instant, datetime):
            usable.append(instant)
        elif isinstance(instant, str):
            parsed = parse_timestamp(instant)
            if parsed is not None:
                usable.append(parsed)
    return max(usable) if usable else None


def _dispatch_task_progress(tasks_root: Path) -> tuple[str, str]:
    """Return a privacy-safe Dispatch task summary and the aggregate state."""
    statuses: list[str] = []
    try:
        for path in tasks_root.glob("*/*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                continue
            status = value.get("status") if isinstance(value, dict) else None
            if isinstance(status, str) and status in {"pending", "in_progress", "completed"}:
                statuses.append(status)
    except OSError:
        return "", "unknown"
    if not statuses:
        return "", "unknown"
    total = len(statuses)
    completed = statuses.count("completed")
    in_progress = statuses.count("in_progress")
    if in_progress:
        state = "working"
        suffix = "進行中"
    elif completed == total:
        state = "result"
        suffix = "已完成"
    else:
        state = "waiting"
        suffix = "待處理"
    return f"{completed}/{total} 完成 · {suffix}", state


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    return value if str(parsed) == value else None


def _codex_thread_details(home: Path, native_ids: Iterable[str]) -> dict[str, CodexThreadDetails]:
    """Read only the visible Codex title and cwd for known local session ids.

    The desktop app keeps thread titles in a small SQLite index, while the
    event JSONL deliberately does not. This query is read-only and selects no
    prompts, previews, summaries, or transcript fields.
    """
    identifiers = tuple(dict.fromkeys(item for item in native_ids if isinstance(item, str) and item))
    if not identifiers:
        return {}

    primary = home / ".codex" / "state_5.sqlite"
    candidates = ([primary] if primary.exists() else []) + [
        path for path in sorted((home / ".codex").glob("state_*.sqlite"), key=lambda path: path.stat().st_mtime, reverse=True)
        if path != primary
    ]
    for database in candidates:
        try:
            connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=0.2)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                if "id" not in columns:
                    continue
                selected_columns = ["id"]
                selected_columns.extend(name for name in ("name", "title", "cwd", "source", "thread_source") if name in columns)
                details: dict[str, CodexThreadDetails] = {}
                for offset in range(0, len(identifiers), 900):
                    part = identifiers[offset:offset + 900]
                    placeholders = ",".join("?" for _ in part)
                    rows = connection.execute(
                        f"SELECT {', '.join(selected_columns)} "
                        f"FROM threads WHERE id IN ({placeholders})", part
                    )
                    for row in rows:
                        row_map = dict(zip(selected_columns, row))
                        native_id = row_map.get("id")
                        if isinstance(native_id, str):
                            details[native_id] = CodexThreadDetails(
                                row_map.get("title"),
                                row_map.get("cwd"),
                                row_map.get("source"),
                                row_map.get("thread_source"),
                                row_map.get("name"),
                            )
                return details
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            continue
    return {}


def _details_from_codex_app_server_data(
    response_data: object, identifiers: Iterable[str],
) -> dict[str, CodexThreadDetails]:
    """Keep only safe display metadata from a ``thread/list`` response."""
    if not isinstance(response_data, list):
        return {}
    wanted = {item for item in identifiers if isinstance(item, str) and item}
    details: dict[str, CodexThreadDetails] = {}
    for value in response_data:
        if not isinstance(value, dict):
            continue
        native_id = value.get("id")
        if not isinstance(native_id, str) or native_id not in wanted:
            continue
        details[native_id] = CodexThreadDetails(
            value.get("title"),
            value.get("cwd"),
            value.get("source"),
            value.get("threadSource"),
            value.get("name"),
        )
    return details


def _codex_app_server_details(native_ids: Iterable[str]) -> dict[str, CodexThreadDetails]:
    """Read current visible task names from Codex's own local app server.

    The SQLite index can retain the original first-message title after Codex has
    renamed a task in its UI.  ``thread/list`` is the same local source used by
    that UI, so it is authoritative for the title that a person sees.  We keep
    only id/name/cwd/source metadata and deliberately ignore every other field
    in the response.
    """
    identifiers = tuple(dict.fromkeys(item for item in native_ids if isinstance(item, str) and item))
    if not identifiers or not _CODEX_APP_SERVER.is_file():
        return {}

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "deskbar-session-titles", "version": "1"}},
    }
    list_threads = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "thread/list",
        "params": {
            "limit": 500,
            "sortKey": "recency_at",
            "sortDirection": "desc",
            "sourceKinds": ["vscode"],
            "useStateDbOnly": False,
        },
    }
    try:
        process = subprocess.Popen(
            [str(_CODEX_APP_SERVER), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if process.stdin is None or process.stdout is None:
        process.terminate()
        return {}

    deadline = time.monotonic() + _CODEX_APP_SERVER_TIMEOUT_SECONDS

    def next_response() -> dict | None:
        """Wait for one JSON-RPC line without letting a broken server block collection."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                return None
            line = process.stdout.readline()
            if not line:
                return None
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            return value if isinstance(value, dict) else None

    try:
        process.stdin.write(json.dumps(initialize, separators=(",", ":")) + "\n")
        process.stdin.flush()
        while True:
            response = next_response()
            if response is None:
                return {}
            if response.get("id") == 1:
                break

        process.stdin.write(json.dumps(list_threads, separators=(",", ":")) + "\n")
        process.stdin.flush()
        while True:
            response = next_response()
            if response is None:
                return {}
            if response.get("id") != 2:
                continue
            payload = response.get("result")
            response_data = payload.get("data") if isinstance(payload, dict) else None
            return _details_from_codex_app_server_data(response_data, identifiers)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.SubprocessError:
            process.kill()


class SessionCollector:
    """Deep collector seam; its output is already safe to push to the Pi."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self.home = home or _current_user_home()
        self.now = now
        self._token_factory = token_factory
        self._open_ids: dict[tuple[str, str], str] = {}
        self._open_targets: dict[str, OpenTarget] = {}

    def collect(self) -> tuple[list[LocalSession], list[SourceProblem]]:
        codex, codex_problems = self._collect_codex()
        claude, claude_problems = self._collect_claude()
        cutoff = self.now().astimezone(timezone.utc)
        newest_by_native_id: dict[tuple[str, str], LocalSession] = {}
        for record in [*codex, *claude]:
            if not (0 <= (cutoff - record.last_active_at).total_seconds() < MAX_ACTIVE_AGE_SECONDS):
                continue
            key = (record.source, record.native_id)
            old = newest_by_native_id.get(key)
            if old is None or record.last_active_at > old.last_active_at:
                newest_by_native_id[key] = record
        records = list(newest_by_native_id.values())
        records.sort(key=lambda record: (-record.last_active_at.timestamp(), record.source, record.native_id))
        # Pi 端也會重新套用這個限制；Mac 端先截斷可避免把不會顯示、
        # 也不會被操作的 session 多送過 tailnet。
        return records[:MAX_ACTIVE_SESSIONS], [*codex_problems, *claude_problems]

    def payload(self) -> dict:
        records, problems = self.collect()
        items = []
        current_open_targets: dict[str, OpenTarget] = {}
        for record in records:
            key = (record.source, record.native_id)
            open_id = self._open_ids.setdefault(key, self._token_factory())
            current_open_targets[open_id] = OpenTarget(record.source, record.native_id)
            item = {
                "source": record.source,
                "label": record.label,
                "project_label": record.project_label,
                "last_active_at": _iso(record.last_active_at),
                "open_id": open_id,
                "activity_state": record.activity_state,
            }
            if record.progress_label:
                item["progress_label"] = record.progress_label
            items.append(item)
        self._open_targets = current_open_targets
        return {
            "items": items,
            "errors": [{"source": problem.source, "code": problem.code} for problem in problems],
            "fetched_at": _iso(self.now()),
        }

    def target_for_open_id(self, open_id: object) -> OpenTarget | None:
        return self._open_targets.get(open_id) if isinstance(open_id, str) else None

    def _collect_codex(self) -> tuple[list[LocalSession], list[SourceProblem]]:
        root = self.home / ".codex" / "sessions"
        if not root.exists():
            return [], [SourceProblem("codex", "unavailable")]
        records: list[LocalSession] = []
        problems: set[str] = set()
        try:
            paths = root.rglob("*.jsonl")
            for path in paths:
                try:
                    first, tail_stamp, activity_state = _json_lines(path)
                    meta = {}
                    if isinstance(first, dict):
                        if first.get("type") == "session_meta" and isinstance(first.get("payload"), dict):
                            meta = first["payload"]
                        elif isinstance(first.get("session_meta"), dict):
                            meta = first["session_meta"]
                        else:
                            meta = first
                    if not isinstance(meta, dict):
                        continue
                    native_id = meta.get("session_id") or meta.get("id")
                    if not isinstance(native_id, str) or not native_id:
                        continue
                    active_at = _best_time(tail_stamp, _mtime(path))
                    if active_at is not None:
                        title_candidate = meta.get("title") or meta.get("customTitle")
                        label, project_label = safe_session_labels(title_candidate, meta.get("cwd"), "未命名 Session")
                        records.append(LocalSession("codex", native_id, label, project_label, active_at, activity_state))
                except PermissionError:
                    problems.add("permission")
                except (OSError, UnicodeError, ValueError):
                    problems.add("corrupt")
        except PermissionError:
            problems.add("permission")
        except OSError:
            problems.add("unavailable")
        native_ids = tuple(record.native_id for record in records)
        # app-server describes the login user's live Codex UI.  Fixture homes
        # and alternate users correctly retain the read-only SQLite fallback.
        try:
            is_login_home = self.home.resolve() == _current_user_home().resolve()
        except OSError:
            is_login_home = False
        app_details = _codex_app_server_details(native_ids) if is_login_home else {}
        sqlite_details = _codex_thread_details(self.home, native_ids)
        # Current UI metadata wins; SQLite fills in anything the app list did
        # not include (for example an older but still-active local JSONL task).
        details = {**sqlite_details, **app_details}
        titled_records: list[LocalSession] = []
        for record in records:
            detail = details.get(record.native_id)
            if detail is not None and detail.is_internal_work_record:
                continue
            label, project_label = safe_session_labels(
                detail.display_title if detail is not None else record.label,
                detail.cwd if detail is not None and detail.cwd else record.project_label,
                "未命名 Session",
            )
            titled_records.append(LocalSession(
                record.source,
                record.native_id,
                label,
                project_label,
                record.last_active_at,
                record.activity_state,
            ))
        return titled_records, [SourceProblem("codex", code) for code in sorted(problems)]

    def _collect_claude(self) -> tuple[list[LocalSession], list[SourceProblem]]:
        projects = self.home / ".claude" / "projects"
        app_sessions = self.home / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
        dispatch_root = self.home / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
        if not projects.exists() and not app_sessions.exists() and not dispatch_root.exists():
            return [], [SourceProblem("claude", "unavailable")]
        found: dict[str, dict] = {}
        problems: set[str] = set()

        def update_candidate(native_id: object, *, title: object = None, custom_title: object = None,
                             cwd: object = None, active_at: datetime | None = None, activity_state: str = "unknown") -> None:
            if not isinstance(native_id, str) or not native_id or active_at is None:
                return
            entry = found.setdefault(native_id, {
                "native_id": native_id,
                "title": None,
                "custom_title": None,
                "cwd": None,
                "active_at": active_at,
                "activity_state": "unknown",
            })
            if title and isinstance(title, str) and title.strip():
                entry["title"] = title
            if custom_title and isinstance(custom_title, str) and custom_title.strip():
                entry["custom_title"] = custom_title
            if cwd and isinstance(cwd, str) and cwd.strip():
                entry["cwd"] = cwd
            if active_at > entry["active_at"]:
                entry["active_at"] = active_at
            if activity_state != "unknown":
                entry["activity_state"] = activity_state

        if projects.exists():
            try:
                for path in projects.rglob("*.jsonl"):
                    try:
                        first, tail_stamp, activity_state = _json_lines(path)
                        if isinstance(first, dict):
                            sid = first.get("sessionId")
                            cust_t = first.get("customTitle")
                            cwd = first.get("cwd")
                            active_at = _best_time(tail_stamp, _mtime(path))
                            update_candidate(sid, custom_title=cust_t, cwd=cwd, active_at=active_at, activity_state=activity_state)
                    except PermissionError:
                        problems.add("permission")
                    except (OSError, UnicodeError, ValueError):
                        problems.add("corrupt")
            except PermissionError:
                problems.add("permission")
            except OSError:
                problems.add("unavailable")

        if app_sessions.exists():
            try:
                for path in app_sessions.rglob("*.json"):
                    try:
                        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                        if isinstance(value, dict):
                            sid = _canonical_uuid(value.get("cliSessionId")) or value.get("sessionId")
                            title = value.get("title")
                            cwd = value.get("cwd")
                            act_state = _classify_event(value)
                            # lastActivityAt is the actual session activity.  A JSON
                            # metadata file can be rewritten by Claude background sync,
                            # so its mtime must be only a fallback, never a newer vote.
                            active_at = parse_timestamp(value.get("lastActivityAt")) or _mtime(path)
                            update_candidate(sid, title=title, cwd=cwd, active_at=active_at, activity_state=act_state)
                    except PermissionError:
                        problems.add("permission")
                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                        problems.add("corrupt")
            except PermissionError:
                problems.add("permission")
            except OSError:
                problems.add("unavailable")

        if dispatch_root.exists():
            try:
                for path in dispatch_root.rglob("local_*.json"):
                    try:
                        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                        if not isinstance(value, dict) or value.get("sessionType") != "dispatch_child":
                            continue
                        active_at = parse_timestamp(value.get("lastActivityAt"))
                        if active_at is None or (self.now().astimezone(timezone.utc) - active_at).total_seconds() >= MAX_ACTIVE_AGE_SECONDS:
                            continue
                        session_id = value.get("sessionId")
                        native_id = _canonical_uuid(value.get("cliSessionId")) or session_id
                        if not isinstance(session_id, str) or not isinstance(native_id, str) or not native_id:
                            continue
                        progress, act_state = _dispatch_task_progress(path.parent / session_id / ".claude" / "tasks")
                        update_candidate(
                            native_id,
                            title=value.get("title"),
                            cwd="Claude Dispatch",
                            active_at=active_at,
                            activity_state=act_state,
                        )
                        found[native_id]["progress_label"] = progress
                    except PermissionError:
                        problems.add("permission")
                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                        problems.add("corrupt")
            except PermissionError:
                problems.add("permission")
            except OSError:
                problems.add("unavailable")

        records: list[LocalSession] = []
        for info in found.values():
            chosen_title = info["title"] or info["custom_title"]
            # Claude can leave behind a queue-operation JSONL with no title and
            # no cwd.  It is not a user-identifiable task, so do not turn it
            # into a misleading "未命名 Session" card.
            if not _clean_label(chosen_title) and not _clean_label(info["cwd"]):
                continue
            label, project_label = safe_session_labels(chosen_title, info["cwd"], "未命名 Session")
            records.append(LocalSession(
                "claude", info["native_id"], label, project_label, info["active_at"],
                info["activity_state"], info.get("progress_label", ""),
            ))

        return records, [SourceProblem("claude", code) for code in sorted(problems)]


class DeskbarClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or None

    def post(self, path: str, payload: dict) -> dict:
        return self._request("POST", path, payload)

    def get(self, path: str) -> dict:
        return self._request("GET", path, None)

    def _request(self, method: str, path: str, payload: dict | None) -> dict:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["X-Deskbar-Token"] = self.token
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        with urlopen(request, timeout=10) as response:  # nosec B310: private, user-configured Deskbar URL
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def open_session_target(source: str, native_id: str | None = None,
                        runner: Callable[..., object] = subprocess.run) -> bool:
    args = APP_OPEN_ARGS.get(source)
    target_id = _canonical_uuid(native_id)
    if source == "codex" and target_id is not None:
        args = ("/usr/bin/open", f"codex://threads/{target_id}")
    elif source == "claude" and target_id is not None:
        args = ("/usr/bin/open", f"claude://resume?session={target_id}")
    if args is None:
        return False
    try:
        result = runner(list(args), check=False, timeout=10, shell=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(result, "returncode", 0) == 0


def open_claude_dispatch(runner: Callable[..., object] = subprocess.run) -> bool:
    """Open Claude's fixed Dispatch route, never a Pi-supplied URL."""
    try:
        result = runner(
            ["/usr/bin/open", "claude://claude.ai/cowork/agent"],
            check=False,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(result, "returncode", 0) == 0


def focus_source_app(source: str, runner: Callable[..., object] = subprocess.run) -> bool:
    return open_session_target(source, None, runner=runner)


class WorkSessionsAgent:
    def __init__(self, collector: SessionCollector, client: DeskbarClient,
                 opener: Callable[[str, str], bool] = open_session_target,
                 dispatch_opener: Callable[[], bool] = open_claude_dispatch) -> None:
        self.collector = collector
        self.client = client
        self.opener = opener
        self.dispatch_opener = dispatch_opener

    def collect_and_push(self) -> dict:
        payload = self.collector.payload()
        self.client.post("/api/work-sessions", payload)
        return payload

    def poll_and_focus(self) -> int:
        response = self.client.get("/api/work-sessions/actions")
        completed = 0
        for action in response.get("actions", []) if isinstance(response, dict) else []:
            if not isinstance(action, dict):
                continue
            action_id = action.get("action_id")
            if not isinstance(action_id, str):
                continue
            source = action.get("source")
            is_dispatch = (
                source == "claude"
                and action.get("kind") == "claude_dispatch"
                and set(action).issubset({"action_id", "source", "kind"})
            )
            opened = False
            if is_dispatch:
                opened = self.dispatch_opener()
            else:
                open_id = action.get("open_id")
                target = self.collector.target_for_open_id(open_id)
                if target is not None and source == target.source:
                    opened = self.opener(target.source, target.native_id)
            # Always ACK invalid/expired local capabilities too: they must never retry forever.
            self.client.post("/api/work-sessions/actions/ack", {"action_id": action_id, "opened": opened})
            completed += 1
        return completed

    def run_forever(self, *, interval: float = COLLECT_SECONDS, poll_interval: float = POLL_SECONDS) -> None:
        next_collect = 0.0
        while True:
            now = time.monotonic()
            try:
                if now >= next_collect:
                    self.collect_and_push()
                    next_collect = now + interval
                self.poll_and_focus()
            except (HTTPError, URLError, HTTPException, OSError, ValueError):
                # Deliberately no exception interpolation: URLs/session data can be private.
                print("[work-sessions] Deskbar 暫時無法同步", flush=True)
            time.sleep(poll_interval)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push safe active Codex/Claude sessions to Deskbar")
    parser.add_argument("--once", action="store_true", help="collect and push once, then exit")
    parser.add_argument("--url", default=os.environ.get("DESKBAR_URL", DEFAULT_URL))
    parser.add_argument("--interval", type=float, default=COLLECT_SECONDS)
    args = parser.parse_args(list(argv) if argv is not None else None)
    agent = WorkSessionsAgent(SessionCollector(), DeskbarClient(args.url, os.environ.get("DESKBAR_PUSH_TOKEN")))
    try:
        if args.once:
            agent.collect_and_push()
            return 0
        agent.run_forever(interval=max(5.0, args.interval))
    except (HTTPError, URLError, HTTPException, OSError, ValueError):
        print("[work-sessions] Deskbar 暫時無法同步", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
