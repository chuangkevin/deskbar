from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from deskbar import config
from deskbar.auth import AuthError, get_access_token, load_accounts
from deskbar.gcal import SyncError, fetch_day_events, fetch_range_events
from deskbar.models import normalize_event
from deskbar.store import AppState
from deskbar.weather import fetch_weather

CAL_INTERVAL, WX_INTERVAL = 300, 1800
WINDOW_PAST_DAYS, WINDOW_FUTURE_DAYS = 7, 30
_get_token = get_access_token          # 測試注入點
_fetch_range = fetch_range_events      # 測試注入點（窗口抓取）
_fetch = fetch_day_events              # 舊版單日別名，保留以免其他引用壞掉

FORCE_SYNC = threading.Event()


def request_sync() -> None:
    """立即觸發下一輪日曆＋天氣同步（例如使用者點擊同步狀態列）。"""
    FORCE_SYNC.set()


@dataclass
class SyncDeps:
    today_fn: object
    now_fn: object
    http_get: object
    http_post: object
    tz: ZoneInfo


def default_deps() -> SyncDeps:
    tz = ZoneInfo("Asia/Taipei")
    return SyncDeps(today_fn=lambda: datetime.now(tz).date(),
                    now_fn=lambda: datetime.now(tz),
                    http_get=requests.get, http_post=requests.post, tz=tz)


def calendar_sync_once(state: AppState, settings, deps: SyncDeps) -> None:
    state.set_syncing(True)
    try:
        accounts = load_accounts(config.accounts_dir())
        emails = {a["email"] for a in accounts}
        for known in list(state.snapshot().statuses):
            if known not in emails:
                state.drop_account(known)
        changed = False
        today: date = deps.today_fn()
        start = today - timedelta(days=WINDOW_PAST_DAYS)
        end = today + timedelta(days=WINDOW_FUTURE_DAYS + 1)
        for acc in accounts:
            email = acc["email"]
            cfg_acc = settings.ensure_account(email)
            if not cfg_acc.calendars:
                for cal in acc.get("calendars", []):
                    cfg_acc.calendars[cal["id"]] = bool(cal.get("primary"))
                changed = True
            try:
                tok = _get_token(acc, http_post=deps.http_post)
                events = []
                for cal_id, enabled in cfg_acc.calendars.items():
                    if not enabled:
                        continue
                    for raw in _fetch_range(tok, cal_id, start, end, deps.tz,
                                            http_get=deps.http_get):
                        e = normalize_event(raw, email, cal_id, deps.tz)
                        if e is not None:
                            events.append(e)
                state.set_events(email, events, deps.now_fn())
            except AuthError:
                state.set_error(email, "需重新授權", deps.now_fn())
            except (SyncError, OSError, ValueError, KeyError, requests.RequestException):
                state.set_error(email, "同步失敗", deps.now_fn())
        if changed:
            config.save_settings(settings)
        state.save_cache()
    finally:
        state.set_syncing(False)


def weather_sync_once(state: AppState, settings, deps: SyncDeps) -> None:
    try:
        w = fetch_weather(settings.weather_lat, settings.weather_lon,
                          settings.weather_label, http_get=deps.http_get,
                          now_fn=deps.now_fn)
        state.set_weather(w)
    except Exception:
        pass  # 保留舊值，UI 顯示資料年齡


def start_threads(state: AppState, settings, settings_lock: threading.Lock) -> None:
    deps = default_deps()

    def cal_loop():
        with settings_lock:
            calendar_sync_once(state, settings, deps)
        elapsed = 0
        while True:
            _time.sleep(1)
            elapsed += 1
            with settings_lock:
                interval_s = settings.sync_interval_min * 60
            if FORCE_SYNC.is_set() or elapsed >= interval_s:
                FORCE_SYNC.clear()
                elapsed = 0
                with settings_lock:
                    calendar_sync_once(state, settings, deps)

    def wx_loop():
        with settings_lock:
            weather_sync_once(state, settings, deps)
        elapsed = 0
        while True:
            _time.sleep(1)
            elapsed += 1
            if FORCE_SYNC.is_set() or elapsed >= WX_INTERVAL:
                elapsed = 0
                with settings_lock:
                    weather_sync_once(state, settings, deps)

    threading.Thread(target=cal_loop, daemon=True).start()
    threading.Thread(target=wx_loop, daemon=True).start()
