from datetime import datetime
from zoneinfo import ZoneInfo
from deskbar.models import normalize_event, event_to_json, event_from_json

TZ = ZoneInfo("Asia/Taipei")


def test_timed_event_utc_converted():
    raw = {
        "id": "e1", "summary": "週會", "status": "confirmed",
        "start": {"dateTime": "2026-07-27T02:00:00Z"},
        "end": {"dateTime": "2026-07-27T03:30:00Z"},
        "location": "會議室",
    }
    e = normalize_event(raw, "a@x.com", "cal1", TZ)
    assert e.title == "週會" and e.account == "a@x.com"
    assert e.start == datetime(2026, 7, 27, 10, 0, tzinfo=TZ)
    assert e.end == datetime(2026, 7, 27, 11, 30, tzinfo=TZ)
    assert e.all_day is False and e.location == "會議室"


def test_all_day_event():
    raw = {"id": "e2", "summary": "繳費", "status": "confirmed",
           "start": {"date": "2026-07-27"}, "end": {"date": "2026-07-28"}}
    e = normalize_event(raw, "a@x.com", "cal1", TZ)
    assert e.all_day is True
    assert e.start == datetime(2026, 7, 27, 0, 0, tzinfo=TZ)
    assert e.end == datetime(2026, 7, 28, 0, 0, tzinfo=TZ)


def test_cancelled_returns_none():
    raw = {"id": "e3", "status": "cancelled",
           "start": {"dateTime": "2026-07-27T02:00:00Z"},
           "end": {"dateTime": "2026-07-27T03:00:00Z"}}
    assert normalize_event(raw, "a@x.com", "c", TZ) is None


def test_untitled_gets_placeholder():
    raw = {"id": "e4", "status": "confirmed",
           "start": {"dateTime": "2026-07-27T02:00:00+08:00"},
           "end": {"dateTime": "2026-07-27T03:00:00+08:00"}}
    assert normalize_event(raw, "a@x.com", "c", TZ).title == "（未命名）"


def test_description_and_location_truncated_at_ingestion():
    raw = {
        "id": "e6", "summary": "長會", "status": "confirmed",
        "start": {"dateTime": "2026-07-27T02:00:00Z"},
        "end": {"dateTime": "2026-07-27T03:00:00Z"},
        "location": "L" * 100,
        "description": "D" * 300,
    }
    e = normalize_event(raw, "a@x.com", "cal1", TZ)
    assert len(e.location) == 80 and e.location == "L" * 80
    assert len(e.description) == 200 and e.description == "D" * 200


def test_description_html_sanitized():
    raw = {
        "id": "e7", "summary": "H", "status": "confirmed",
        "start": {"dateTime": "2026-07-27T02:00:00Z"},
        "end": {"dateTime": "2026-07-27T03:00:00Z"},
        "description": (
            '看<a href="https://example.com">連結</a>來 A &amp; B<br>第二段'
            "<p>第三段</p>"
        ),
    }
    e = normalize_event(raw, "a@x.com", "cal1", TZ)
    assert "<" not in e.description and ">" not in e.description
    assert "&amp;" not in e.description
    assert "A & B" in e.description          # 實體已還原
    assert "連結" in e.description             # 標籤剝掉、內文保留
    assert "href" not in e.description
    assert "第二段" in e.description and "第三段" in e.description
    # <br>/<p> 轉成的斷點最終被壓縮成單一空白，不留下多餘換行或連續空白
    assert "\n" not in e.description
    assert "  " not in e.description


def test_location_html_sanitized():
    raw = {
        "id": "e8", "summary": "H", "status": "confirmed",
        "start": {"dateTime": "2026-07-27T02:00:00Z"},
        "end": {"dateTime": "2026-07-27T03:00:00Z"},
        "location": '<b>會議室</b> A &amp; B 館',
    }
    e = normalize_event(raw, "a@x.com", "cal1", TZ)
    assert "<" not in e.location and ">" not in e.location
    assert e.location == "會議室 A & B 館"


def test_json_roundtrip():
    raw = {"id": "e5", "summary": "T", "status": "confirmed",
           "start": {"dateTime": "2026-07-27T02:00:00Z"},
           "end": {"dateTime": "2026-07-27T03:00:00Z"}}
    e = normalize_event(raw, "a@x.com", "c", TZ)
    assert event_from_json(event_to_json(e)) == e
