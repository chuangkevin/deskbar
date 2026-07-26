from datetime import date
from zoneinfo import ZoneInfo
import pytest
from deskbar import gcal
from deskbar.auth import AuthError

TZ = ZoneInfo("Asia/Taipei")


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload

    def json(self):
        return self._p


def test_fetch_paginated():
    pages = [FakeResp(200, {"items": [{"id": "1"}], "nextPageToken": "p2"}),
             FakeResp(200, {"items": [{"id": "2"}]})]
    urls = []

    def get(url, params=None, headers=None, timeout=None):
        urls.append(params)
        return pages.pop(0)

    items = gcal.fetch_day_events("tok", "cal1", date(2026, 7, 27), TZ, http_get=get)
    assert [i["id"] for i in items] == ["1", "2"]
    assert urls[0]["timeMin"] == "2026-07-27T00:00:00+08:00"
    assert urls[0]["timeMax"] == "2026-07-28T00:00:00+08:00"
    assert urls[0]["singleEvents"] == "true"
    assert urls[1]["pageToken"] == "p2"


def test_401_raises_autherror():
    def get(url, params=None, headers=None, timeout=None):
        return FakeResp(401, {})

    with pytest.raises(AuthError):
        gcal.fetch_day_events("tok", "cal1", date(2026, 7, 27), TZ, http_get=get)


def test_other_error_raises_syncerror():
    def get(url, params=None, headers=None, timeout=None):
        return FakeResp(500, {})

    with pytest.raises(gcal.SyncError):
        gcal.fetch_day_events("tok", "cal1", date(2026, 7, 27), TZ, http_get=get)
