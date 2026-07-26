from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, date, time
from zoneinfo import ZoneInfo


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
    return Event(
        id=raw.get("id", ""),
        account=account,
        calendar_id=calendar_id,
        title=raw.get("summary") or "（未命名）",
        start=start,
        end=end,
        all_day=all_day,
        location=raw.get("location"),
        description=raw.get("description"),
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
