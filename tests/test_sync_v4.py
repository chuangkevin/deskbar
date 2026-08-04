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


def test_request_sync_sets_both_independent_events_no_race(monkeypatch):
    """舊版單一 FORCE_SYNC 事件被 cal_loop／wx_loop 共用：先醒來的那個 loop 一
    clear() 掉，另一個就永遠等不到（race）。現在 FORCE_CAL/FORCE_WX 各自獨立，
    模擬 cal_loop 消費完只 clear 自己的，FORCE_WX 應該不受影響、仍是 set 狀態。"""
    sync.FORCE_CAL.clear()
    sync.FORCE_WX.clear()
    sync.request_sync()
    assert sync.FORCE_CAL.is_set()
    assert sync.FORCE_WX.is_set()

    # 模擬 cal_loop 消費（跟 start_threads.cal_loop 一樣：check-and-clear 自己的事件）
    if sync.FORCE_CAL.is_set():
        sync.FORCE_CAL.clear()

    assert not sync.FORCE_CAL.is_set()
    assert sync.FORCE_WX.is_set(), "wx_loop 還沒消費，FORCE_WX 不該被 cal_loop 誤清掉"
    sync.FORCE_WX.clear()


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


def test_retry_delays_sequence_capped():
    assert sync._next_retry_elapsed(0) is None
    assert sync._next_retry_elapsed(1) == 15
    assert sync._next_retry_elapsed(2) == 30
    assert sync._next_retry_elapsed(3) == 60
    assert sync._next_retry_elapsed(4) == 120
    assert sync._next_retry_elapsed(5) == 300
    assert sync._next_retry_elapsed(99) == 300, "退避封頂不再更長"


def test_calendar_sync_returns_false_on_fetch_failure(tmp_path, monkeypatch):
    def boom(tok, cal, start, end, tz, http_get):
        raise OSError("dns down")

    deps = _deps(monkeypatch, tmp_path, None)
    monkeypatch.setattr(sync, "_fetch_range", boom)
    _acc_file(config.accounts_dir())
    state, settings = AppState(), Settings()
    assert sync.calendar_sync_once(state, settings, deps) is False
    st = state.snapshot().statuses["a@x.com"]
    assert st.ok is False and st.error == "同步失敗"


def test_calendar_sync_returns_true_on_success(tmp_path, monkeypatch):
    deps = _deps(monkeypatch, tmp_path, lambda start, end, cal: [])
    _acc_file(config.accounts_dir())
    state, settings = AppState(), Settings()
    assert sync.calendar_sync_once(state, settings, deps) is True


def test_weather_sync_returns_false_then_true(monkeypatch, tmp_path):
    calls = []

    def flaky_get(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("dns down")
        return FakeResp(200, {
            "current": {"temperature_2m": 22.0, "weather_code": 1,
                        "apparent_temperature": 21.0, "relative_humidity_2m": 60},
            "daily": {"temperature_2m_max": [25.0], "temperature_2m_min": [18.0],
                      "sunrise": ["2026-07-27T05:00:00"], "sunset": ["2026-07-27T19:00:00"]}})

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path / "cache"))
    deps = sync.SyncDeps(today_fn=lambda: TODAY, now_fn=lambda: NOW,
                         http_get=flaky_get, http_post=None, tz=TZ)
    state, settings = AppState(), Settings()
    settings.weather_auto_locate = False
    assert sync.weather_sync_once(state, settings, deps) is False
    assert sync.weather_sync_once(state, settings, deps) is True


def test_linear_sync_returns_false_on_failure_then_true(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    settings.linear_api_key = "lk"
    calls = []

    def flaky_fetch(key):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("dns down")
        return []

    monkeypatch.setattr("deskbar.linear.fetch_issues", flaky_fetch)
    state = AppState()
    assert sync.linear_sync_once(state, settings) is False
    assert sync.linear_sync_once(state, settings) is True
    settings.linear_api_key = ""


def test_sync_loop_pure_decision():
    # _next_retry_elapsed 已由 test_retry_delays_sequence_capped 覆蓋；
    # 這條驗證「失敗會觸發重試、成功會重置」是由 _try_once 回傳值驅動。
    calls = []

    def boom():
        calls.append(1)
        raise OSError("x")

    streak = sync._try_once(boom, 0)
    assert streak == 1
    streak = sync._try_once(boom, streak)
    assert streak == 2
    assert sync._try_once(lambda: True, streak) == 0
    assert sync._try_once(lambda: False, 0) == 1
