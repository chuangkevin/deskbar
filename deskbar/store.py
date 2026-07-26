from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime

from deskbar import config
from deskbar.models import Event, event_from_json, event_to_json
from deskbar.weather import Weather


@dataclass(frozen=True)
class AccountStatus:
    email: str
    ok: bool
    error: str | None
    last_sync: datetime | None


@dataclass(frozen=True)
class Snapshot:
    events: list[Event]
    weather: Weather | None
    statuses: dict[str, AccountStatus]
    seq: int
    syncing: bool = False


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self._events: dict[str, list[Event]] = {}
        self._weather: Weather | None = None
        self._statuses: dict[str, AccountStatus] = {}
        self._seq = 0
        self._syncing = False

    def snapshot(self) -> Snapshot:
        with self._lock:
            events = [e for lst in self._events.values() for e in lst]
            events.sort(key=lambda e: (e.start, e.id))
            return Snapshot(events, self._weather, dict(self._statuses), self._seq,
                            self._syncing)

    def set_syncing(self, v: bool) -> None:
        with self._lock:
            self._syncing = v
            self._seq += 1

    def set_events(self, email: str, events: list[Event], now: datetime) -> None:
        with self._lock:
            self._events[email] = list(events)
            self._statuses[email] = AccountStatus(email, True, None, now)
            self._seq += 1

    def set_error(self, email: str, msg: str, now: datetime) -> None:
        with self._lock:
            old = self._statuses.get(email)
            self._statuses[email] = AccountStatus(
                email, False, msg, old.last_sync if old else None)
            self._seq += 1

    def drop_account(self, email: str) -> None:
        with self._lock:
            self._events.pop(email, None)
            self._statuses.pop(email, None)
            self._seq += 1

    def set_weather(self, w: Weather) -> None:
        with self._lock:
            self._weather = w
            self._seq += 1

    def save_cache(self) -> None:
        with self._lock:
            data = {e: [event_to_json(x) for x in lst] for e, lst in self._events.items()}
        p = config.cache_dir() / "events.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def load_cache(self) -> None:
        p = config.cache_dir() / "events.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        with self._lock:
            for email, lst in data.items():
                try:
                    self._events[email] = [event_from_json(d) for d in lst]
                except (KeyError, TypeError, ValueError):
                    continue
            self._seq += 1
