from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from deskbar import config
from deskbar.models import Event, event_from_json, event_to_json
from deskbar.presence import PresenceState
from deskbar.weather import Weather

_DEFAULT_PRESENCE = PresenceState(present=True, rssi=None, last_seen=None, enabled=False)

if TYPE_CHECKING:      # 只給型別檢查用，避免 store.py 平白多一條 runtime 依賴到 claudeusage
    from deskbar.claudeusage import UsageInfo


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
    presence: PresenceState = _DEFAULT_PRESENCE
    usage: "UsageInfo | None" = None
    linear: list = field(default_factory=list)        # LinearIssue 清單（待辦卡）
    linear_at: datetime | None = None                  # 上次成功同步時間


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self._events: dict[str, list[Event]] = {}
        self._weather: Weather | None = None
        self._statuses: dict[str, AccountStatus] = {}
        self._seq = 0
        self._syncing = False
        self._usage: "UsageInfo | None" = None
        self._presence: PresenceState = _DEFAULT_PRESENCE
        self._linear: list = []
        self._linear_at: datetime | None = None
        self._cached_snapshot: Snapshot | None = None
        self._cached_seq: int | None = None

    def snapshot(self) -> Snapshot:
        """render 每格都會呼叫；事件全量重排序在幾百筆時不算貴，但沒必要每格白做。
        只要 _seq 沒變（沒有任何 set_* 呼叫發生），就回傳上次建好的快取。"""
        with self._lock:
            if self._cached_snapshot is not None and self._cached_seq == self._seq:
                return self._cached_snapshot
            events = [e for lst in self._events.values() for e in lst]
            events.sort(key=lambda e: (e.start, e.id))
            snap = Snapshot(events, self._weather, dict(self._statuses), self._seq,
                            self._syncing, self._presence, self._usage,
                            list(self._linear), self._linear_at)
            self._cached_snapshot = snap
            self._cached_seq = self._seq
            return snap

    def bump(self) -> None:
        """外部資料（如便條）變更時叫醒 render 迴圈：只推進 seq，不改任何欄位。"""
        with self._lock:
            self._seq += 1

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

    def set_usage(self, info: "UsageInfo") -> None:
        with self._lock:
            self._usage = info
            self._seq += 1

    def set_linear(self, items: list, now: datetime) -> None:
        with self._lock:
            self._linear = list(items)
            self._linear_at = now
            self._seq += 1

    def set_presence(self, ps: PresenceState) -> None:
        with self._lock:
            self._presence = ps
            self._seq += 1

    def save_cache(self) -> None:
        """原子寫入（tempfile + os.replace），比照 config.save_settings：斷電/例外中斷
        時舊的 events.json 維持完好，不會留下截斷內容讓下次 load_cache 讀到壞資料。"""
        with self._lock:
            data = {e: [event_to_json(x) for x in lst] for e, lst in self._events.items()}
        cache_dir = config.cache_dir()
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, cache_dir / "events.json")

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
