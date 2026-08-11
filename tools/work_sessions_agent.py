#!/usr/bin/env python3
"""Mac-side collector for Deskbar's display-safe active-session panel.

It intentionally treats Codex and Claude files as private implementation
details.  It reads only identifiers, timestamps and cwd to make a basename;
conversation text is neither returned, logged nor sent to the Pi.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
POLL_SECONDS = 5.0
COLLECT_SECONDS = 15.0
APP_OPEN_ARGS = {
    "codex": ("/usr/bin/open", "-a", "ChatGPT"),
    "claude": ("/usr/bin/open", "-a", "Claude"),
}
_TAIL_BYTES = 128 * 1024


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


@dataclass(frozen=True)
class LocalSession:
    source: str
    native_id: str
    label: str
    last_active_at: datetime


@dataclass(frozen=True)
class SourceProblem:
    source: str
    code: str


def _json_lines(path: Path) -> tuple[dict | None, datetime | None]:
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

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - _TAIL_BYTES))
        tail = handle.read()
    for raw_line in reversed(tail.splitlines()):
        try:
            value = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            stamp = parse_timestamp(value.get("timestamp"))
            if stamp is not None:
                return first, stamp
    return first, None


def _best_time(*instants: datetime | None) -> datetime | None:
    usable = [instant for instant in instants if instant is not None]
    return max(usable) if usable else None


class SessionCollector:
    """Deep collector seam; its output is already safe to push to the Pi."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self.home = home or Path.home()
        self.now = now
        self._token_factory = token_factory
        self._open_ids: dict[tuple[str, str], str] = {}
        self._open_sources: dict[str, str] = {}

    def collect(self) -> tuple[list[LocalSession], list[SourceProblem]]:
        codex, codex_problems = self._collect_codex()
        claude, claude_problems = self._collect_claude()
        cutoff = self.now().astimezone(timezone.utc)
        records = [record for record in [*codex, *claude]
                   if 0 <= (cutoff - record.last_active_at).total_seconds() < MAX_ACTIVE_AGE_SECONDS]
        records.sort(key=lambda record: (-record.last_active_at.timestamp(), record.source, record.native_id))
        # Pi 端也會重新套用這個限制；Mac 端先截斷可避免把不會顯示、
        # 也不會被操作的 session 多送過 tailnet。
        return records[:MAX_ACTIVE_SESSIONS], [*codex_problems, *claude_problems]

    def payload(self) -> dict:
        records, problems = self.collect()
        items = []
        current_open_ids: dict[str, str] = {}
        for record in records:
            key = (record.source, record.native_id)
            open_id = self._open_ids.setdefault(key, self._token_factory())
            current_open_ids[open_id] = record.source
            items.append({
                "source": record.source,
                "label": record.label,
                "last_active_at": _iso(record.last_active_at),
                "open_id": open_id,
            })
        self._open_sources = current_open_ids
        return {
            "items": items,
            "errors": [{"source": problem.source, "code": problem.code} for problem in problems],
            "fetched_at": _iso(self.now()),
        }

    def source_for_open_id(self, open_id: object) -> str | None:
        return self._open_sources.get(open_id) if isinstance(open_id, str) else None

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
                    first, tail_stamp = _json_lines(path)
                    meta = first.get("session_meta", {}) if isinstance(first, dict) else {}
                    if not isinstance(meta, dict):
                        continue
                    native_id = meta.get("session_id") or meta.get("id")
                    if not isinstance(native_id, str) or not native_id:
                        continue
                    active_at = _best_time(tail_stamp, _mtime(path))
                    if active_at is not None:
                        records.append(LocalSession("codex", native_id, safe_project_label(meta.get("cwd")), active_at))
                except PermissionError:
                    problems.add("permission")
                except (OSError, UnicodeError, ValueError):
                    problems.add("corrupt")
        except PermissionError:
            problems.add("permission")
        except OSError:
            problems.add("unavailable")
        return records, [SourceProblem("codex", code) for code in sorted(problems)]

    def _collect_claude(self) -> tuple[list[LocalSession], list[SourceProblem]]:
        projects = self.home / ".claude" / "projects"
        app_sessions = self.home / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
        if not projects.exists() and not app_sessions.exists():
            return [], [SourceProblem("claude", "unavailable")]
        found: dict[str, LocalSession] = {}
        problems: set[str] = set()

        def remember(native_id: object, cwd: object, active_at: datetime | None) -> None:
            if not isinstance(native_id, str) or not native_id or active_at is None:
                return
            candidate = LocalSession("claude", native_id, safe_project_label(cwd), active_at)
            old = found.get(native_id)
            if old is None or candidate.last_active_at > old.last_active_at:
                found[native_id] = candidate

        if projects.exists():
            try:
                for path in projects.glob("*/*.jsonl"):
                    try:
                        first, tail_stamp = _json_lines(path)
                        if isinstance(first, dict):
                            remember(first.get("sessionId"), first.get("cwd"), _best_time(tail_stamp, _mtime(path)))
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
                for path in app_sessions.glob("*/*/*.json"):
                    try:
                        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                        if isinstance(value, dict):
                            remember(value.get("sessionId"), value.get("cwd"), _best_time(
                                parse_timestamp(value.get("lastActivityAt")), _mtime(path)))
                    except PermissionError:
                        problems.add("permission")
                    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                        problems.add("corrupt")
            except PermissionError:
                problems.add("permission")
            except OSError:
                problems.add("unavailable")
        return list(found.values()), [SourceProblem("claude", code) for code in sorted(problems)]


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


def focus_source_app(source: str, runner: Callable[..., object] = subprocess.run) -> bool:
    args = APP_OPEN_ARGS.get(source)
    if args is None:
        return False
    try:
        result = runner(list(args), check=False, timeout=10, shell=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(result, "returncode", 0) == 0


class WorkSessionsAgent:
    def __init__(self, collector: SessionCollector, client: DeskbarClient,
                 opener: Callable[[str], bool] = focus_source_app) -> None:
        self.collector, self.client, self.opener = collector, client, opener

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
            action_id, open_id, source = action.get("action_id"), action.get("open_id"), action.get("source")
            if not isinstance(action_id, str):
                continue
            if source == self.collector.source_for_open_id(open_id):
                self.opener(source)
            # Always ACK invalid/expired local capabilities too: they must never retry forever.
            self.client.post("/api/work-sessions/actions/ack", {"action_id": action_id})
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
            except (HTTPError, URLError, OSError, ValueError):
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
    except (HTTPError, URLError, OSError, ValueError):
        print("[work-sessions] Deskbar 暫時無法同步", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
