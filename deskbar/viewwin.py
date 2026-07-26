"""視圖窗口純函數：依顯示寬度（span）與錨點時間，算出渲染窗口 [win_start, win_end)。

不依賴 pygame／store，純時間運算，方便單元測試。app.py／dashboard.py 共用。
"""
from __future__ import annotations

from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

SPAN_ORDER = ["half", "day", "week", "month"]

# 已同步資料的實際涵蓋範圍：[今天−7 天, 今天+30 天]（含端點）。
# 與 sync.py 的抓取窗口定義為同一份數字（sync 從這裡匯入），避免兩處漂移。
WINDOW_PAST_DAYS, WINDOW_FUTURE_DAYS = 7, 30


def view_window(span: str, anchor: datetime, tz: ZoneInfo, *,
                start_hour: int = 8, end_hour: int = 24) -> tuple[datetime, datetime]:
    """回傳 (win_start, win_end)：

    - half：錨點 −2h ～ +10h
    - day：錨點所在日 start_hour:00 ～ end_hour:00（end_hour=24 即次日 00:00）
    - week：錨點所在週的週一 00:00 ～ 下週一 00:00
    - month：錨點所在月 1 號 00:00 ～ 次月 1 號 00:00
    """
    if span == "half":
        return anchor - timedelta(hours=2), anchor + timedelta(hours=10)
    if span == "day":
        d = anchor.date()
        midnight = datetime.combine(d, _time(0, 0), tzinfo=tz)
        start = midnight + timedelta(hours=start_hour)
        end = midnight + timedelta(hours=end_hour)
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


def agenda_window(span: str, anchor_or_now: datetime, tz: ZoneInfo) -> tuple[_date, int]:
    """行程模式（一天一塊直欄，v4.1）視窗：回傳 (start_date, n_days)。

    - half/day：單欄＝錨點所在日，n_days=1。
    - week/month：錨點所在週對齊週一起算（跟 view_window 的 week 分支同一套
      對齊規則），n_days=7——月檔在行程模式下鋪的是「一週寬的 7 欄」，跟河道
      month 檔的整月計數格網是不同的呈現（見 spec 第 11 節 v4.1）。
    """
    anchor_date = anchor_or_now.date()
    if span in ("half", "day"):
        return anchor_date, 1
    if span in ("week", "month"):
        monday = anchor_date - timedelta(days=anchor_or_now.weekday())
        return monday, 7
    raise ValueError(f"未知的顯示寬度: {span!r}")


def next_span(span: str) -> str:
    """右上寬度鈕循環順序：half→day→week→month→half。未知值安全回退到 half。"""
    if span not in SPAN_ORDER:
        return "half"
    i = SPAN_ORDER.index(span)
    return SPAN_ORDER[(i + 1) % len(SPAN_ORDER)]


def clamp_anchor(anchor: datetime, today: datetime, tz: ZoneInfo) -> datetime:
    """平移結果限制在資料窗口邊界內：[今天−7 天 00:00, 今天＋30 天 23:59:59]。"""
    lo = datetime.combine(today.date() - timedelta(days=WINDOW_PAST_DAYS), _time(0, 0), tzinfo=tz)
    hi = datetime.combine(today.date() + timedelta(days=WINDOW_FUTURE_DAYS), _time(23, 59, 59),
                          tzinfo=tz)
    if anchor < lo:
        return lo
    if anchor > hi:
        return hi
    return anchor


def data_window(today: _date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """已同步資料的實際涵蓋範圍：[今天−7 天 00:00, 今天+31 天 00:00)（不含端點）。

    與 sync.calendar_sync_once 抓取的 [start, end) 完全一致，供 UI（月/週/半天/日視圖）
    標示「資料窗口外＝假空」用，避免把「還沒同步」誤畫成「真的沒事」。
    """
    start = datetime.combine(today - timedelta(days=WINDOW_PAST_DAYS), _time(0, 0), tzinfo=tz)
    end = datetime.combine(today + timedelta(days=WINDOW_FUTURE_DAYS + 1), _time(0, 0), tzinfo=tz)
    return start, end


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
