"""視圖窗口純函數：依顯示寬度（span）與錨點時間，算出渲染窗口 [win_start, win_end)。

不依賴 pygame／store，純時間運算，方便單元測試。app.py／dashboard.py 共用。
"""
from __future__ import annotations

from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

SPAN_ORDER = ["half", "day", "week", "month"]


def view_window(span: str, anchor: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """回傳 (win_start, win_end)：

    - half：錨點 −2h ～ +10h
    - day：錨點所在日 08:00 ～ 24:00（次日 00:00）
    - week：錨點所在週的週一 00:00 ～ 下週一 00:00
    - month：錨點所在月 1 號 00:00 ～ 次月 1 號 00:00
    """
    if span == "half":
        return anchor - timedelta(hours=2), anchor + timedelta(hours=10)
    if span == "day":
        d = anchor.date()
        start = datetime.combine(d, _time(8, 0), tzinfo=tz)
        end = datetime.combine(d, _time(0, 0), tzinfo=tz) + timedelta(hours=24)
        return start, end
    if span == "week":
        monday = anchor.date() - timedelta(days=anchor.weekday())
        start = datetime.combine(monday, _time(0, 0), tzinfo=tz)
        return start, start + timedelta(days=7)
    if span == "month":
        first = anchor.date().replace(day=1)
        start = datetime.combine(first, _time(0, 0), tzinfo=tz)
        nxt = (_date(first.year + 1, 1, 1) if first.month == 12
               else first.replace(month=first.month + 1))
        return start, datetime.combine(nxt, _time(0, 0), tzinfo=tz)
    raise ValueError(f"未知的顯示寬度: {span!r}")


def next_span(span: str) -> str:
    """右上寬度鈕循環順序：half→day→week→month→half。未知值安全回退到 half。"""
    if span not in SPAN_ORDER:
        return "half"
    i = SPAN_ORDER.index(span)
    return SPAN_ORDER[(i + 1) % len(SPAN_ORDER)]


def clamp_anchor(anchor: datetime, today: datetime, tz: ZoneInfo) -> datetime:
    """平移結果限制在資料窗口邊界內：[今天−7 天 00:00, 今天＋30 天 23:59:59]。"""
    lo = datetime.combine(today.date() - timedelta(days=7), _time(0, 0), tzinfo=tz)
    hi = datetime.combine(today.date() + timedelta(days=30), _time(23, 59, 59), tzinfo=tz)
    if anchor < lo:
        return lo
    if anchor > hi:
        return hi
    return anchor


def window_label(span: str, anchor: datetime, win_start: datetime, win_end: datetime) -> str:
    """頂部中央顯示用的窗口標籤文字，例如「7月20日–7月26日」「2026年7月」「7月26日 半天」。"""
    if span == "half":
        return f"{anchor.month}月{anchor.day}日 半天"
    if span == "day":
        return f"{anchor.month}月{anchor.day}日"
    if span == "week":
        last = win_end - timedelta(days=1)
        return f"{win_start.month}月{win_start.day}日–{last.month}月{last.day}日"
    if span == "month":
        return f"{win_start.year}年{win_start.month}月"
    return ""
