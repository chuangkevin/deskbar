"""便條牆資料層：個人即棄 scratch（antinote 哲學——臨時、無組織、看完即撕）。

輸入端在鍵盤（Mac shell function / 手機網頁 POST /api/notes），deskbar 只是
落點與提醒面；螢幕上的操作只有「撕掉」（兩段點擊確認）。
存 config_dir/notes.json，原子寫入（比照 alarms/settings）；上限 30 張、
每張 500 字——這是便條牆不是筆記庫，滿了擠掉最舊的。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from deskbar import config

TZ = ZoneInfo("Asia/Taipei")
MAX_NOTES = 30
MAX_TEXT = 500


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    ts: str          # ISO8601（含時區），顯示端自行格式化


def _path():
    return config.config_dir() / "notes.json"


class NotesStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._notes: list[Note] = []      # 新的在前

    def load(self) -> None:
        try:
            raw = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        out = []
        for d in raw if isinstance(raw, list) else []:
            try:
                out.append(Note(str(d["id"]), str(d["text"])[:MAX_TEXT],
                                str(d["ts"])))
            except (KeyError, TypeError):
                continue
        with self._lock:
            self._notes = out[:MAX_NOTES]

    def _save_locked(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=config.config_dir(), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([asdict(n) for n in self._notes], f, ensure_ascii=False,
                      indent=1)
        os.replace(tmp, _path())

    def list(self) -> list:
        with self._lock:
            return list(self._notes)

    def add(self, text: str) -> "Note | None":
        text = (text or "").strip()[:MAX_TEXT]
        if not text:
            return None
        n = Note(uuid.uuid4().hex[:8], text, datetime.now(TZ).isoformat())
        with self._lock:
            self._notes.insert(0, n)
            del self._notes[MAX_NOTES:]          # 滿了擠掉最舊
            self._save_locked()
        return n

    def remove(self, nid: str) -> bool:
        with self._lock:
            before = len(self._notes)
            self._notes = [n for n in self._notes if n.id != nid]
            if len(self._notes) != before:
                self._save_locked()
                return True
        return False
