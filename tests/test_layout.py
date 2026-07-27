from datetime import date, datetime
from zoneinfo import ZoneInfo
from deskbar.layout import Rect, layout_timeline, layout_timeline_range, time_to_x, split_allday
from deskbar.models import Event

TZ = ZoneInfo("Asia/Taipei")
DAY = date(2026, 7, 27)
AREA = Rect(0, 0, 1600, 300)


def ev(eid, account, h1, m1, h2, m2, all_day=False):
    return Event(eid, account, "c", eid,
                 datetime(2026, 7, 27, h1, m1, tzinfo=TZ),
                 datetime(2026, 7, 27, h2, m2, tzinfo=TZ), all_day, None, None)


def test_time_to_x_linear():
    assert time_to_x(datetime(2026, 7, 27, 8, 0, tzinfo=TZ), DAY, 8, 24, 0, 1600) == 0
    assert time_to_x(datetime(2026, 7, 27, 16, 0, tzinfo=TZ), DAY, 8, 24, 0, 1600) == 800


def test_two_lanes_vertical_split():
    placed, of = layout_timeline([ev("a", "A", 9, 0, 10, 0), ev("b", "B", 9, 0, 10, 0)],
                                 ["A", "B"], DAY, 8, 24, AREA)
    assert not of
    ra = next(p for p in placed if p.event.id == "a").rect
    rb = next(p for p in placed if p.event.id == "b").rect
    assert ra.y == 0 and ra.h == 150
    assert rb.y == 150 and rb.h == 150


def test_overlap_sublanes_same_account():
    placed, _ = layout_timeline([ev("a", "A", 9, 0, 11, 0), ev("b", "A", 10, 0, 12, 0)],
                                ["A"], DAY, 8, 24, AREA)
    ra = next(p for p in placed if p.event.id == "a").rect
    rb = next(p for p in placed if p.event.id == "b").rect
    assert ra.y == 0 and rb.y == 150  # 兩條子車道均分 300
    assert ra.h == rb.h == 150


def test_clip_before_start():
    placed, _ = layout_timeline([ev("a", "A", 7, 0, 9, 0)], ["A"], DAY, 8, 24, AREA)
    p = placed[0]
    assert p.rect.x == 0 and p.clip_l and not p.clip_r
    assert abs(p.rect.w - 100) < 1e-6  # 08–09 = 1h = 100px


def test_overflow_beyond_max_sublanes():
    evs = [ev(str(i), "A", 9, 0, 10, 0) for i in range(5)]
    placed, of = layout_timeline(evs, ["A"], DAY, 8, 24, AREA, max_sublanes=3)
    assert len(placed) == 3 and len(of) == 2


def test_zero_duration_event_gets_min_width_10px():
    """極短（甚至零長度）事件的色塊仍要有起碼的可觸控／可視寬度：
    最小寬度從 6.0 調到 10.0px（配合量測式標題截斷，太窄乾脆不畫字）。"""
    win_start = datetime(2026, 7, 27, 8, 0, tzinfo=TZ)
    win_end = datetime(2026, 7, 28, 0, 0, tzinfo=TZ)
    zero = ev("z", "A", 9, 0, 9, 0)
    placed, _ = layout_timeline_range([zero], ["A"], win_start, win_end, AREA)
    assert placed[0].rect.w == 10.0


def test_split_allday():
    ad, timed = split_allday([ev("a", "A", 9, 0, 10, 0), ev("b", "A", 0, 0, 0, 0, all_day=True)])
    assert [e.id for e in ad] == ["b"] and [e.id for e in timed] == ["a"]


# ---------------------------------------------------------------- v2：叢集分高＋整日列

def _mk(idx, acc, h1, m1, h2, m2):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Taipei")
    return Event(f"e{idx}", acc, "c", f"事件{idx}",
                 datetime(2026, 7, 28, h1, m1, tzinfo=tz),
                 datetime(2026, 7, 28, h2, m2, tzinfo=tz), False, None, None)


def _win():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Taipei")
    return (datetime(2026, 7, 28, 8, 0, tzinfo=tz),
            datetime(2026, 7, 29, 0, 0, tzinfo=tz))


def test_overlapping_events_never_share_pixels_and_standalone_stays_full_height():
    """v2 回歸鎖（實機回報「多個行程會重疊」＋「沒有正確顯示」）：
    重疊事件必須分子列（矩形兩兩不相交）；叢集外的單獨事件維持整泳道高。"""
    ws, we = _win()
    area = Rect(420, 52, 1100, 368)
    evs = [_mk(1, "a@x", 9, 0, 10, 0),          # 單獨
           _mk(2, "a@x", 11, 0, 12, 30),        # 與 3 重疊
           _mk(3, "a@x", 11, 30, 12, 0),
           _mk(4, "a@x", 15, 0, 16, 0)]         # 單獨
    placed, overflow = layout_timeline_range(evs, ["a@x"], ws, we, area)
    assert not overflow
    rects = {p.event.id: p.rect for p in placed}
    lane_h = area.h
    assert abs(rects["e1"].h - lane_h) < 1, "叢集外單獨事件維持整泳道高"
    assert abs(rects["e4"].h - lane_h) < 1
    assert abs(rects["e2"].h - lane_h / 2) < 1, "重疊叢集內部平分高度"
    for a in placed:
        for b in placed:
            if a.event.id >= b.event.id:
                continue
            ax, bx = a.rect, b.rect
            overlap = not (ax.x + ax.w <= bx.x or bx.x + bx.w <= ax.x
                           or ax.y + ax.h <= bx.y or bx.y + bx.h <= ax.y)
            assert not overlap, f"{a.event.id} 與 {b.event.id} 矩形重疊"


def test_allday_strip_reserves_top_of_lane():
    from deskbar.layout import ALLDAY_STRIP_H
    ws, we = _win()
    area = Rect(420, 52, 1100, 368)
    evs = [_mk(1, "a@x", 9, 0, 10, 0)]
    placed, _ = layout_timeline_range(evs, ["a@x", "b@x"], ws, we, area,
                                      allday_accounts={"a@x"})
    r = placed[0].rect
    lane_h = area.h / 2
    assert abs(r.y - (area.y + ALLDAY_STRIP_H)) < 1, "計時卡從整日列之下開始"
    assert abs(r.h - (lane_h - ALLDAY_STRIP_H)) < 1
    placed2, _ = layout_timeline_range(evs, ["a@x", "b@x"], ws, we, area)
    assert abs(placed2[0].rect.y - area.y) < 1, "沒有整日事件的帳號不預留"
