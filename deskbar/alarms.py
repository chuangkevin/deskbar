from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from deskbar import config


@dataclass
class Alarm:
    id: str
    time: str            # "HH:MM"
    days: list[int]      # Python weekday 0=Mon；[] = 一次性
    label: str
    enabled: bool = True


class AlarmStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._alarms: list[Alarm] = []

    def _path(self):
        return config.config_dir() / "alarms.json"

    def load(self) -> None:
        with self._lock:
            try:
                raw = json.loads(self._path().read_text(encoding="utf-8"))
                self._alarms = [Alarm(**a) for a in raw]
            except (OSError, ValueError, TypeError):
                self._alarms = []

    def _save_locked(self) -> None:
        self._path().write_text(
            json.dumps([asdict(a) for a in self._alarms], ensure_ascii=False, indent=1),
            encoding="utf-8")

    def list(self) -> list[Alarm]:
        with self._lock:
            return [Alarm(**asdict(a)) for a in self._alarms]

    def add(self, time: str, days: list[int], label: str) -> Alarm:
        a = Alarm(id=uuid.uuid4().hex[:8], time=time, days=sorted(days), label=label)
        with self._lock:
            self._alarms.append(a)
            self._save_locked()
        return a

    def remove(self, alarm_id: str) -> bool:
        with self._lock:
            n = len(self._alarms)
            self._alarms = [a for a in self._alarms if a.id != alarm_id]
            if len(self._alarms) != n:
                self._save_locked()
                return True
            return False

    def set_enabled(self, alarm_id: str, enabled: bool) -> bool:
        with self._lock:
            for a in self._alarms:
                if a.id == alarm_id:
                    a.enabled = enabled
                    self._save_locked()
                    return True
            return False

    def due(self, last: datetime | None, now: datetime) -> list[Alarm]:
        fired: list[Alarm] = []
        with self._lock:
            for a in self._alarms:
                if not a.enabled:
                    continue
                hh, mm = a.time.split(":")
                fire = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                if not (last is not None and last < fire <= now):
                    continue
                if a.days and fire.weekday() not in a.days:
                    continue
                fired.append(Alarm(**asdict(a)))
                if not a.days:
                    a.enabled = False
                    self._save_locked()
        return fired
