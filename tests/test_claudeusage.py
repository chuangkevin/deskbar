"""deskbar.claudeusage：純資料層測試。usage 資料改由 Mac agent 推送
（見 deskbar.webserver 的 POST /api/usage），這支模組不再做任何網路呼叫，
只剩 UsageInfo 資料形狀與 fmt_countdown 倒數格式化純函數。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from deskbar import claudeusage

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


# ---------------------------------------------------------------- UsageInfo


def test_usage_info_holds_all_fields():
    info = claudeusage.UsageInfo(
        session_pct=42.0, session_resets_at=NOW + timedelta(hours=2),
        weekly_pct=61.5, weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=12.0, fable_resets_at=NOW + timedelta(hours=1),
        fetched_at=NOW,
    )
    assert info.session_pct == 42.0
    assert info.weekly_pct == 61.5
    assert info.fable_pct == 12.0
    assert info.fetched_at == NOW


def test_usage_info_fields_may_be_none():
    info = claudeusage.UsageInfo(None, None, None, None, None, None, fetched_at=NOW)
    assert info.session_pct is None
    assert info.session_resets_at is None
    assert info.weekly_pct is None
    assert info.weekly_resets_at is None
    assert info.fable_pct is None
    assert info.fable_resets_at is None


def test_usage_info_is_frozen():
    info = claudeusage.UsageInfo(None, None, None, None, None, None, fetched_at=NOW)
    try:
        info.session_pct = 1.0
        assert False, "UsageInfo 應該是 frozen dataclass，不該能就地修改"
    except AttributeError:
        pass


# ---------------------------------------------------------------- fmt_countdown


def test_fmt_countdown_days():
    assert claudeusage.fmt_countdown(NOW + timedelta(days=1, hours=4), NOW) == "1d 4h"


def test_fmt_countdown_hours_minutes():
    assert claudeusage.fmt_countdown(NOW + timedelta(hours=2, minutes=3), NOW) == "2h 03m"


def test_fmt_countdown_imminent():
    assert claudeusage.fmt_countdown(NOW + timedelta(seconds=30), NOW) == "即將重置"
    assert claudeusage.fmt_countdown(NOW - timedelta(seconds=5), NOW) == "即將重置"


def test_fmt_countdown_none():
    assert claudeusage.fmt_countdown(None, NOW) == "—"
