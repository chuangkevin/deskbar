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


def time_to_x_range(dt: datetime, win_start: datetime, win_end: datetime,
                    x0: float, x1: float) -> float:
    """任意 datetime 窗口版：dt 在 [win_start, win_end] 內對應到 [x0, x1] 的像素位置。

    超出窗口的 dt 會被夾在 x0/x1（呼叫端可另外用 clip_l/clip_r 判斷是否裁切）。
    """
    total = (win_end - win_start).total_seconds()
    if total <= 0:
        return x0
    sec = (dt - win_start).total_seconds()
    return x0 + max(0.0, min(1.0, sec / total)) * (x1 - x0)


def time_to_x(dt: datetime, day: date, start_hour: int, end_hour: int,
              x0: float, x1: float) -> float:
    win_start = datetime.combine(day, _time(0), tzinfo=dt.tzinfo) + timedelta(hours=start_hour)
    win_end = datetime.combine(day, _time(0), tzinfo=dt.tzinfo) + timedelta(hours=end_hour)
    return time_to_x_range(dt, win_start, win_end, x0, x1)


def split_allday(events: list[Event]) -> tuple[list[Event], list[Event]]:
    ad = [e for e in events if e.all_day]
    timed = [e for e in events if not e.all_day]
    return ad, timed


ALLDAY_STRIP_H = 34     # 泳道頂部整日列高度（該帳號有整日事件時才保留）


def layout_timeline_range(timed: list[Event], lane_order: list[str],
                         win_start: datetime, win_end: datetime, area: Rect,
                         max_sublanes: int = 3,
                         allday_accounts: "set | None" = None
                         ) -> tuple[list[Placed], list[Event]]:
    """任意 datetime 窗口版泳道佈局（2026-07-28 v2）：

    - 整日列預留：allday_accounts 內的帳號，泳道頂部保留 ALLDAY_STRIP_H 給
      整日膠囊，計時卡從其下開始——v1 讓膠囊浮在卡上（實機回報「會重疊」）。
    - 叢集局部分高：只有「彼此重疊的事件叢集」內部才分割高度，叢集外的
      單獨事件維持整條泳道高——v1 是全泳道統一分高，窗口內任何一處重疊
      就把所有卡砍半（實機回報「沒有正確顯示」）。
    """
    placed: list[Placed] = []
    overflow: list[Event] = []
    n = max(1, len(lane_order))
    lane_h = area.h / n
    allday_accounts = allday_accounts or set()
    for li, email in enumerate(lane_order):
        strip = ALLDAY_STRIP_H if email in allday_accounts else 0
        lane_y = area.y + li * lane_h + strip
        usable_h = max(24.0, lane_h - strip)
        evs = sorted((e for e in timed if e.account == email),
                     key=lambda e: (e.start, e.end))
        # 先切「重疊叢集」：依開始時間掃描，start < 叢集目前最大結束 ⇒ 同叢集。
        clusters: list[list[Event]] = []
        cluster_max_end = None
        for e in evs:
            if cluster_max_end is not None and e.start < cluster_max_end:
                clusters[-1].append(e)
                cluster_max_end = max(cluster_max_end, e.end)
            else:
                clusters.append([e])
                cluster_max_end = e.end
        for cluster in clusters:
            sub_end: list[datetime] = []      # 叢集內每條子列目前的最後結束時間
            assign: list[tuple[Event, int]] = []
            for e in cluster:
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
            sub_h = usable_h / used
            for e, si in assign:
                x0 = time_to_x_range(e.start, win_start, win_end, area.x, area.x + area.w)
                x1 = time_to_x_range(e.end, win_start, win_end, area.x, area.x + area.w)
                clip_l = e.start < win_start
                clip_r = e.end > win_end
                w = max(10.0, x1 - x0)
                y = lane_y + si * sub_h
                placed.append(Placed(e, Rect(x0, y, w, sub_h), clip_l, clip_r))
    return placed, overflow


def layout_timeline(timed: list[Event], lane_order: list[str], day: date,
                    start_hour: int, end_hour: int, area: Rect,
                    max_sublanes: int = 3) -> tuple[list[Placed], list[Event]]:
    tz = next((e.start.tzinfo for e in timed), None)
    win_start = datetime.combine(day, _time(0), tzinfo=tz) + timedelta(hours=start_hour)
    win_end = datetime.combine(day, _time(0), tzinfo=tz) + timedelta(hours=end_hour)
    return layout_timeline_range(timed, lane_order, win_start, win_end, area, max_sublanes)
