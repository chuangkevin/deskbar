"""Linear 待辦同步：GraphQL viewer.assignedIssues → LinearIssue 清單。

- 認證走個人 API Key（Linear→Settings→Security & access→Personal API keys），
  由手機網頁貼入、存裝置 settings.json（0600），永不進 repo、不進 log。
  Linear 個人金鑰放 Authorization 原值（不是 Bearer 前綴）。
- 「Pi 純展示機」鐵則下的合法例外，比照 weather：輕量唯讀輪詢、失敗保留
  舊資料。解析是純函式，測試餵假 payload。
- 排序＝Linear 桌面的直覺：緊急(1)→高(2)→中(3)→低(4)→無(0)，同級比
  到期日（無到期日排後），再比 identifier。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

GQL_URL = "https://api.linear.app/graphql"
QUERY = """{ viewer { assignedIssues(
  first: 40,
  filter: { state: { type: { nin: ["completed", "canceled"] } } }
) { nodes {
  identifier title priority dueDate
  state { name type color }
  project { name }
} } } }"""

_FALLBACK_COLOR = (140, 146, 164)


@dataclass(frozen=True)
class LinearIssue:
    identifier: str          # 例如 SARA-123
    title: str
    state_name: str          # 例如 In Progress
    state_type: str          # backlog/unstarted/started/…
    state_color: str         # Linear 給的 "#5e6ad2" 十六進位字串
    priority: int            # 0=無 1=緊急 2=高 3=中 4=低
    due: "date | None"
    project: str


def state_rgb(hex_color: str) -> tuple:
    """"#5e6ad2" → (94,106,210)；壞字串回中性灰，不炸。"""
    try:
        s = hex_color.lstrip("#")
        if len(s) == 6:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError):
        pass
    return _FALLBACK_COLOR


def _prio_rank(p: int) -> int:
    return 5 if p == 0 else p        # 「無優先度」排最後


def parse_issues(payload: dict) -> list:
    nodes = (((payload or {}).get("data") or {}).get("viewer") or {}) \
        .get("assignedIssues", {}).get("nodes", [])
    out: list[LinearIssue] = []
    for n in nodes:
        if not isinstance(n, dict) or not n.get("identifier"):
            continue
        due = None
        raw_due = n.get("dueDate")
        if isinstance(raw_due, str):
            try:
                due = date.fromisoformat(raw_due[:10])
            except ValueError:
                due = None
        st = n.get("state") or {}
        out.append(LinearIssue(
            identifier=str(n["identifier"]),
            title=str(n.get("title") or "")[:200],
            state_name=str(st.get("name") or "—"),
            state_type=str(st.get("type") or ""),
            state_color=str(st.get("color") or ""),
            priority=n.get("priority") if isinstance(n.get("priority"), int) else 0,
            due=due,
            project=str((n.get("project") or {}).get("name") or ""),
        ))
    out.sort(key=lambda i: (_prio_rank(i.priority),
                            i.due or date.max, i.identifier))
    return out


def save_cache(items: list, fetched_at: datetime) -> None:
    """待辦快取落地（比照 events.json）：重開機先端出上次的牆，不用等首次
    同步。原子寫入；失敗靜默（快取是加分項不是必需品）。"""
    from deskbar import config
    try:
        data = {"fetched_at": fetched_at.isoformat(),
                "items": [dict(asdict(i), due=i.due.isoformat() if i.due else None)
                          for i in items]}
        d = config.cache_dir()
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, d / "linear.json")
    except OSError:
        pass


def load_cache() -> "tuple[list, datetime | None]":
    from deskbar import config
    try:
        raw = json.loads((config.cache_dir() / "linear.json").read_text(encoding="utf-8"))
        items = []
        for d in raw.get("items", []):
            due = d.get("due")
            items.append(LinearIssue(
                identifier=str(d["identifier"]), title=str(d["title"]),
                state_name=str(d["state_name"]), state_type=str(d["state_type"]),
                state_color=str(d["state_color"]), priority=int(d["priority"]),
                due=date.fromisoformat(due) if due else None,
                project=str(d.get("project", ""))))
        at = datetime.fromisoformat(raw["fetched_at"])
        return items, at
    except (OSError, ValueError, KeyError, TypeError):
        return [], None


def fetch_issues(api_key: str, http_post=requests.post,
                 now_fn=lambda: datetime.now(ZoneInfo("Asia/Taipei"))) -> list:
    resp = http_post(GQL_URL, json={"query": QUERY}, headers={
        "Authorization": api_key,          # 個人金鑰不加 Bearer 前綴
        "Content-Type": "application/json",
    }, timeout=20)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        # 金鑰無效等 GraphQL 層錯誤：raise 讓 sync 保留舊資料並記 stderr
        raise RuntimeError(str(body["errors"])[:200])
    return parse_issues(body)
