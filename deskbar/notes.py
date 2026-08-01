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
    color: int = -1  # -1=自動（依 id 雜湊輪色）；0..4=使用者指定的色盤索引


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
                color = d.get("color", -1)
                if not isinstance(color, int) or isinstance(color, bool) \
                        or not (-1 <= color <= 4):
                    color = -1
                out.append(Note(str(d["id"]), str(d["text"])[:MAX_TEXT],
                                str(d["ts"]), color))
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

    def update(self, nid: str, text: str) -> "Note | None":
        """編輯便條內文（保留原 ts 與顏色——ts 是「捕捉時刻」）。空文字拒改。"""
        return self.patch(nid, text=text)

    def patch(self, nid: str, text=None, color=None) -> "Note | None":
        """改內文和/或顏色（一次原子完成）。text 空字串拒改；color 限 -1..4
        （-1=回到自動輪色）。兩者都 None 或都非法回 None。"""
        if text is not None:
            text = (text or "").strip()[:MAX_TEXT]
            if not text:
                return None
        if color is not None and (not isinstance(color, int)
                                  or isinstance(color, bool)
                                  or not (-1 <= color <= 4)):
            return None
        if text is None and color is None:
            return None
        with self._lock:
            for i, n in enumerate(self._notes):
                if n.id == nid:
                    new = Note(n.id, text if text is not None else n.text,
                               n.ts, color if color is not None else n.color)
                    self._notes[i] = new
                    self._save_locked()
                    return new
        return None

    def reorder(self, ids: list) -> bool:
        """依給定 id 順序整批重排（網頁拖動排序；順序＝優先序，牆上第一張
        ＝第 1 優先）。未列出的 id 排在後面、維持原相對順序；未知 id 忽略。
        回傳是否真的變動（沒變就不寫檔、呼叫端不用 bump 重繪）。"""
        with self._lock:
            by_id = {n.id: n for n in self._notes}
            listed = set(x for x in ids if x in by_id)
            new = [by_id[x] for x in ids if x in by_id] \
                + [n for n in self._notes if n.id not in listed]
            if [n.id for n in new] == [n.id for n in self._notes]:
                return False
            self._notes = new
            self._save_locked()
            return True

    def remove(self, nid: str) -> bool:
        with self._lock:
            before = len(self._notes)
            self._notes = [n for n in self._notes if n.id != nid]
            if len(self._notes) != before:
                self._save_locked()
                return True
        return False
