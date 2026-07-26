from __future__ import annotations
import html
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date, time
from zoneinfo import ZoneInfo


MAX_DESCRIPTION_LEN = 200
MAX_LOCATION_LEN = 80

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"(?i)<br\s*/?>|</?p\b[^>]*>")
_WS_RE = re.compile(r"\s+")


def _clean_rich_text(text: str, convert_breaks: bool) -> str:
    """Google Calendar 的 description/location 常帶 HTML（<a href>、<br>、
    <p>、&amp; 之類的實體）——桌面小工具沒有 HTML 渲染能力，全部清成純文字：

    1. （僅 description）先把 <br>/<p> 系列標籤換成換行，保留段落之間的斷點，
       不然標籤剝掉後兩段文字會黏在一起變成一個字。
    2. 去除所有剩下的標籤（<a href="...">連結</a> 之類，只留內文文字）。
    3. html.unescape 還原 &amp;/&nbsp; 等實體。
    4. 壓縮連續空白（含步驟 1 產生的換行）成單一空白，維持單行顯示。
    """
    if convert_breaks:
        text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


@dataclass(frozen=True)
class Event:
    id: str
    account: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    description: str | None


def _parse_side(side: dict, tz: ZoneInfo) -> tuple[datetime, bool]:
    if "dateTime" in side:
        dt = datetime.fromisoformat(side["dateTime"].replace("Z", "+00:00"))
        return dt.astimezone(tz), False
    d = date.fromisoformat(side["date"])
    return datetime.combine(d, time(0, 0), tzinfo=tz), True


def normalize_event(raw: dict, account: str, calendar_id: str, tz: ZoneInfo) -> Event | None:
    if raw.get("status") == "cancelled":
        return None
    try:
        start, all_day = _parse_side(raw["start"], tz)
        end, _ = _parse_side(raw["end"], tz)
    except (KeyError, ValueError):
        return None
    location = raw.get("location")
    if location is not None:
        location = _clean_rich_text(location, convert_breaks=False)[:MAX_LOCATION_LEN]
    description = raw.get("description")
    if description is not None:
        description = _clean_rich_text(description, convert_breaks=True)[:MAX_DESCRIPTION_LEN]
    return Event(
        id=raw.get("id", ""),
        account=account,
        calendar_id=calendar_id,
        title=raw.get("summary") or "（未命名）",
        start=start,
        end=end,
        all_day=all_day,
        location=location,
        description=description,
    )


def event_to_json(e: Event) -> dict:
    d = asdict(e)
    d["start"] = e.start.isoformat()
    d["end"] = e.end.isoformat()
    return d


def event_from_json(d: dict) -> Event:
    d = dict(d)
    d["start"] = datetime.fromisoformat(d["start"])
    d["end"] = datetime.fromisoformat(d["end"])
    return Event(**d)
