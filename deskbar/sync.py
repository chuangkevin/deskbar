from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from deskbar import config
from deskbar.auth import AuthError, get_access_token, load_accounts
from deskbar.gcal import SyncError, fetch_day_events
from deskbar.models import normalize_event
from deskbar.store import AppState
from deskbar.weather import fetch_weather

CAL_INTERVAL, WX_INTERVAL = 300, 1800
_get_token = get_access_token          # 測試注入點
_fetch = fetch_day_events


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
    accounts = load_accounts(config.accounts_dir())
    emails = {a["email"] for a in accounts}
    for known in list(state.snapshot().statuses):
        if known not in emails:
            state.drop_account(known)
    changed = False
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
            day = deps.today_fn()
            for cal_id, enabled in cfg_acc.calendars.items():
                if not enabled:
                    continue
                for raw in _fetch(tok, cal_id, day, deps.tz, http_get=deps.http_get):
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
        while True:
            with settings_lock:
                calendar_sync_once(state, settings, deps)
            _time.sleep(CAL_INTERVAL)

    def wx_loop():
        while True:
            with settings_lock:
                weather_sync_once(state, settings, deps)
            _time.sleep(WX_INTERVAL)

    threading.Thread(target=cal_loop, daemon=True).start()
    threading.Thread(target=wx_loop, daemon=True).start()
