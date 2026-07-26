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
