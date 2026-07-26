from dataclasses import dataclass
from dataclasses import dataclass as _dc
from datetime import date, datetime, time as _time, timedelta

from deskbar.models import Event


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


@_dc(frozen=True)
class Placed:
    event: Event
    rect: Rect
    clip_l: bool
    clip_r: bool


def time_to_x(dt: datetime, day: date, start_hour: int, end_hour: int,
              x0: float, x1: float) -> float:
    day_start = datetime.combine(day, _time(0), tzinfo=dt.tzinfo) + timedelta(hours=start_hour)
    total = (end_hour - start_hour) * 3600.0
    sec = (dt - day_start).total_seconds()
    return x0 + max(0.0, min(1.0, sec / total)) * (x1 - x0)


def split_allday(events: list[Event]) -> tuple[list[Event], list[Event]]:
    ad = [e for e in events if e.all_day]
    timed = [e for e in events if not e.all_day]
    return ad, timed


def layout_timeline(timed: list[Event], lane_order: list[str], day: date,
                    start_hour: int, end_hour: int, area: Rect,
                    max_sublanes: int = 3) -> tuple[list[Placed], list[Event]]:
    placed: list[Placed] = []
    overflow: list[Event] = []
    n = max(1, len(lane_order))
    lane_h = area.h / n
    for li, email in enumerate(lane_order):
        evs = sorted((e for e in timed if e.account == email), key=lambda e: (e.start, e.end))
        sub_end: list[datetime] = []          # 每條子車道目前的最後結束時間
        assign: list[tuple[Event, int]] = []
        for e in evs:
            for si, endt in enumerate(sub_end):
                if endt <= e.start:
                    sub_end[si] = e.end
                    assign.append((e, si))
                    break
            else:
                if len(sub_end) < max_sublanes:
                    sub_end.append(e.end)
                    assign.append((e, len(sub_end) - 1))
                else:
                    overflow.append(e)
        used = max((si for _, si in assign), default=0) + 1
        sub_h = lane_h / used
        for e, si in assign:
            x0 = time_to_x(e.start, day, start_hour, end_hour, area.x, area.x + area.w)
            x1 = time_to_x(e.end, day, start_hour, end_hour, area.x, area.x + area.w)
            clip_l = time_to_x(e.start, day, start_hour, end_hour, 0, 1) == 0 and \
                e.start < datetime.combine(day, _time(start_hour), tzinfo=e.start.tzinfo)
            clip_r = e.end > datetime.combine(day, _time(0), tzinfo=e.end.tzinfo) + timedelta(hours=end_hour)
            w = max(6.0, x1 - x0)
            y = area.y + li * lane_h + si * sub_h
            placed.append(Placed(e, Rect(x0, y, w, sub_h), clip_l, clip_r))
    return placed, overflow
