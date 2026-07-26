from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from deskbar import config

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class Alarm:
    id: str
    time: str            # "HH:MM"
    days: list[int]      # Python weekday 0=Mon；[] = 一次性
    label: str
    enabled: bool = True


def _normalize_alarm(raw: object) -> Alarm | None:
    """驗證/修復一筆從 alarms.json 讀入的原始資料。

    id/time 壞掉或缺失視為不可修復，回傳 None（該筆會被捨棄）。
    其餘欄位盡量修復：days 只保留 0..6 的唯一整數（排序），label 轉字串並
    截斷 40 字，enabled 非 bool 時預設 True。任何非預期的例外都視為壞資料。
    """
    try:
        if not isinstance(raw, dict):
            return None
        aid = raw.get("id")
        if not isinstance(aid, str) or not aid:
            return None
        time_s = raw.get("time")
        if not isinstance(time_s, str) or not _TIME_RE.match(time_s):
            return None
        days_raw = raw.get("days")
        days: list[int] = []
        if isinstance(days_raw, list):
            seen: set[int] = set()
            for d in days_raw:
                if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 \
                        and d not in seen:
                    seen.add(d)
                    days.append(d)
            days.sort()
        label = raw.get("label")
        if not isinstance(label, str):
            label = ""
        label = label[:40]
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            enabled = True
        return Alarm(id=aid, time=time_s, days=days, label=label, enabled=enabled)
    except Exception:
        return None


class AlarmStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._alarms: list[Alarm] = []

    def _path(self):
        return config.config_dir() / "alarms.json"

    def load(self) -> None:
        """從 alarms.json 載入鬧鐘，永不拋例外——壞掉的記錄會被修復或捨棄。"""
        with self._lock:
            try:
                raw = json.loads(self._path().read_text(encoding="utf-8"))
            except Exception:
                self._alarms = []
                return
            if not isinstance(raw, list):
                self._alarms = []
                return
            self._alarms = [a for a in (_normalize_alarm(item) for item in raw)
                             if a is not None]

    def _save_locked(self) -> None:
        """原子寫入（tempfile + os.replace），比照 config.save_settings：半途出例外
        （例如 json.dump 中途拋錯）不會留下截斷的 alarms.json，舊檔內容維持完好。"""
        fd, tmp = tempfile.mkstemp(dir=config.config_dir(), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in self._alarms], f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path())

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

    def toggle(self, alarm_id: str) -> bool:
        """在既有 lock 下原子翻轉 enabled，避免與 Flask thread／due() 自動停用互相競爭。"""
        with self._lock:
            for a in self._alarms:
                if a.id == alarm_id:
                    a.enabled = not a.enabled
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
