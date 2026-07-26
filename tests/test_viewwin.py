from datetime import datetime
from zoneinfo import ZoneInfo

from deskbar.viewwin import clamp_anchor, next_span, view_window, window_label

TZ = ZoneInfo("Asia/Taipei")


def test_half_window_spans_across_midnight():
    # 錨點 2026-07-27 01:30 → -2h ~ +10h 跨過午夜前後
    anchor = datetime(2026, 7, 27, 1, 30, tzinfo=TZ)
    start, end = view_window("half", anchor, TZ)
    assert start == datetime(2026, 7, 26, 23, 30, tzinfo=TZ)
    assert end == datetime(2026, 7, 27, 11, 30, tzinfo=TZ)


def test_day_window_is_08_to_24():
    anchor = datetime(2026, 7, 27, 15, 0, tzinfo=TZ)
    start, end = view_window("day", anchor, TZ)
    assert start == datetime(2026, 7, 27, 8, 0, tzinfo=TZ)
    assert end == datetime(2026, 7, 28, 0, 0, tzinfo=TZ)


def test_day_window_honors_custom_start_end_hour():
    # settings.start_hour/end_hour 曾經是死參數（day 檔永遠硬編碼 08–24）；
    # 現在 view_window 要真的套用傳進來的自訂值。
    anchor = datetime(2026, 7, 27, 15, 0, tzinfo=TZ)
    start, end = view_window("day", anchor, TZ, start_hour=6, end_hour=22)
    assert start == datetime(2026, 7, 27, 6, 0, tzinfo=TZ)
    assert end == datetime(2026, 7, 27, 22, 0, tzinfo=TZ)


def test_week_window_starts_monday():
    # 2026-07-27 是週一
    monday = datetime(2026, 7, 27, 9, 0, tzinfo=TZ)
    start, end = view_window("week", monday, TZ)
    assert start == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
    assert end == datetime(2026, 8, 3, 0, 0, tzinfo=TZ)

    # 週中任一天（週四）算出的窗口應與週一相同
    thursday = datetime(2026, 7, 30, 22, 0, tzinfo=TZ)
    start2, end2 = view_window("week", thursday, TZ)
    assert (start2, end2) == (start, end)


def test_month_window_handles_year_boundary():
    anchor = datetime(2026, 12, 15, 12, 0, tzinfo=TZ)
    start, end = view_window("month", anchor, TZ)
    assert start == datetime(2026, 12, 1, 0, 0, tzinfo=TZ)
    assert end == datetime(2027, 1, 1, 0, 0, tzinfo=TZ)


def test_month_window_mid_year():
    anchor = datetime(2026, 7, 5, 3, 0, tzinfo=TZ)
    start, end = view_window("month", anchor, TZ)
    assert start == datetime(2026, 7, 1, 0, 0, tzinfo=TZ)
    assert end == datetime(2026, 8, 1, 0, 0, tzinfo=TZ)


def test_next_span_cycles():
    assert next_span("half") == "day"
    assert next_span("day") == "week"
    assert next_span("week") == "month"
    assert next_span("month") == "half"
    assert next_span("banana") == "half"   # 未知值安全回退


def test_clamp_anchor_within_bounds_unchanged():
    today = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)
    inside = datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert clamp_anchor(inside, today, TZ) == inside


def test_clamp_anchor_clamps_past_and_future():
    today = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)
    too_early = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
    too_late = datetime(2026, 12, 1, 0, 0, tzinfo=TZ)
    lo = clamp_anchor(too_early, today, TZ)
    hi = clamp_anchor(too_late, today, TZ)
    assert lo == datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    assert hi == datetime(2026, 8, 26, 23, 59, 59, tzinfo=TZ)


def test_window_label_formats():
    assert window_label("half", datetime(2026, 7, 26, 10, 0, tzinfo=TZ), None, None) \
        == "7月26日 半天"
    assert window_label("day", datetime(2026, 7, 26, 10, 0, tzinfo=TZ), None, None) \
        == "7月26日"
    start = datetime(2026, 7, 20, 0, 0, tzinfo=TZ)
    end = datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
    assert window_label("week", start, start, end) == "7月20日–7月26日"
    mstart = datetime(2026, 7, 1, 0, 0, tzinfo=TZ)
    mend = datetime(2026, 8, 1, 0, 0, tzinfo=TZ)
    assert window_label("month", mstart, mstart, mend) == "2026年7月"
