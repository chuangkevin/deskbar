from datetime import date, datetime, time, timedelta
from urllib.parse import quote

import requests

from deskbar.auth import AuthError

BASE = "https://www.googleapis.com/calendar/v3/calendars"


class SyncError(Exception):
    pass


def fetch_day_events(access_token: str, calendar_id: str, day: date, tz,
                     http_get=requests.get) -> list[dict]:
    t0 = datetime.combine(day, time(0), tzinfo=tz)
    params = {
        "timeMin": t0.isoformat(),
        "timeMax": (t0 + timedelta(days=1)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "250",
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{BASE}/{quote(calendar_id)}/events"
    items: list[dict] = []
    while True:
        resp = http_get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 401:
            raise AuthError(f"{calendar_id}: 401")
        if resp.status_code != 200:
            raise SyncError(f"{calendar_id}: HTTP {resp.status_code}")
        body = resp.json()
        items.extend(body.get("items", []))
        nxt = body.get("nextPageToken")
        if not nxt:
            return items
        params["pageToken"] = nxt
