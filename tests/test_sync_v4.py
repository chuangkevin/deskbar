import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from deskbar import config, gcal, sync
from deskbar.config import Settings
from deskbar.store import AppState

TZ = ZoneInfo("Asia/Taipei")
TODAY = date(2026, 7, 27)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


def _acc_file(dir, email="a@x.com"):
    (dir / f"{email}.json").write_text(json.dumps({
        "email": email, "refresh_token": "rt", "client_id": "c", "client_secret": "s",
        "calendars": [{"id": email, "summary": "主要", "primary": True}],
    }), encoding="utf-8")


def _deps(monkeypatch, tmp_path, fetch_result):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(sync, "_get_token", lambda acc, http_post: "tok")
    monkeypatch.setattr(sync, "_fetch_range",
                        lambda tok, cal, start, end, tz, http_get: fetch_result(start, end, cal))
    return sync.SyncDeps(today_fn=lambda: TODAY, now_fn=lambda: NOW,
                         http_get=None, http_post=None, tz=TZ)


def test_range_window(tmp_path, monkeypatch):
    seen = []

    def fetch_result(start, end, cal):
        seen.append((start, end))
        return []

    deps = _deps(monkeypatch, tmp_path, fetch_result)
    _acc_file(config.accounts_dir())
    state, settings = AppState(), Settings()
    sync.calendar_sync_once(state, settings, deps)

    assert seen, "沒有呼叫 _fetch_range"
    starts = [s for s, _ in seen]
    ends = [e for _, e in seen]
    assert min(starts) == TODAY - timedelta(days=7)
    assert max(ends) == TODAY + timedelta(days=31)


def test_syncing_flag(tmp_path, monkeypatch):
    calls = []
    orig = AppState.set_syncing

    def spy(self, v):
        calls.append(v)
        return orig(self, v)

    monkeypatch.setattr(AppState, "set_syncing", spy)
    deps = _deps(monkeypatch, tmp_path, lambda start, end, cal: [])
    _acc_file(config.accounts_dir())
    state, settings = AppState(), Settings()
    sync.calendar_sync_once(state, settings, deps)

    assert calls == [True, False]
    assert state.snapshot().syncing is False


def test_settings_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    s.view_span = "banana"
    s.sync_interval_min = 0
    config.save_settings(s)
    s2 = config.load_settings()
    assert s2.view_span == "day"
    assert s2.sync_interval_min == 5


def test_settings_validation_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    s.view_mode = "teleport"
    s.sync_interval_min = 999
    config.save_settings(s)
    s2 = config.load_settings()
    assert s2.view_mode == "lanes"
    assert s2.sync_interval_min == 5


def test_request_sync_sets_event(monkeypatch):
    sync.FORCE_SYNC.clear()
    assert not sync.FORCE_SYNC.is_set()
    sync.request_sync()
    assert sync.FORCE_SYNC.is_set()
    sync.FORCE_SYNC.clear()


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._p = payload

    def json(self):
        return self._p


def test_fetch_range_events_window_bounds():
    urls = []

    def get(url, params=None, headers=None, timeout=None):
        urls.append(params)
        return FakeResp(200, {"items": [{"id": "1"}]})

    start = date(2026, 7, 20)
    end = date(2026, 8, 27)
    items = gcal.fetch_range_events("tok", "cal1", start, end, TZ, http_get=get)
    assert [i["id"] for i in items] == ["1"]
    assert urls[0]["timeMin"] == "2026-07-20T00:00:00+08:00"
    assert urls[0]["timeMax"] == "2026-08-27T00:00:00+08:00"
    assert urls[0]["singleEvents"] == "true"
    assert urls[0]["orderBy"] == "startTime"
    assert urls[0]["maxResults"] == "250"
