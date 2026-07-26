from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from deskbar import config
from deskbar.auth import AuthError, get_access_token, load_accounts
from deskbar.gcal import SyncError, fetch_range_events
from deskbar.models import normalize_event
from deskbar.store import AppState
from deskbar.weather import fetch_weather

CAL_INTERVAL, WX_INTERVAL = 300, 1800
# 注意：這兩個數字與 deskbar.viewwin.WINDOW_PAST_DAYS/WINDOW_FUTURE_DAYS 定義必須一致——
# 那邊是 UI 用來判斷「資料窗口外＝假空」的邊界，這邊是實際抓取的窗口，兩者本來就該是同一份窗口。
WINDOW_PAST_DAYS, WINDOW_FUTURE_DAYS = 7, 30
_get_token = get_access_token          # 測試注入點
_fetch_range = fetch_range_events      # 測試注入點（窗口抓取）

# 分成兩個獨立事件：同一顆「強制同步」事件曾被 cal_loop／wx_loop 共用，
# 先醒來的那個 loop 會把事件 clear 掉，另一個永遠等不到（race）。
# 現在 request_sync() 同時 set 兩個，各 loop 只 check-and-clear 自己的。
FORCE_CAL = threading.Event()
FORCE_WX = threading.Event()
FORCE_SYNC = FORCE_CAL     # 舊名相容別名（deprecated，新程式碼請用 FORCE_CAL）


def request_sync() -> None:
    """立即觸發下一輪日曆＋天氣同步（例如使用者點擊同步狀態列）。"""
    FORCE_CAL.set()
    FORCE_WX.set()


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


def calendar_sync_once(state: AppState, settings, deps: SyncDeps,
                       settings_lock: threading.Lock | None = None) -> None:
    """三階段同步，刻意把網路 I/O 挪到鎖外，避免長時間凍結 UI 觸控：

    (a) 持鎖：快照每帳號設定（啟用中的日曆 id 清單）、註冊新帳號（含預設啟用主曆、
        寫回 settings）——這段不碰網路，很快。
    (b) 不持鎖：token 刷新＋依窗口抓事件＋normalize——真正花時間的網路階段。
    (c) 不需再碰 settings；state.set_events/set_error 自己有內部鎖，直接呼叫即可。
    """
    if settings_lock is None:
        settings_lock = threading.Lock()
    state.set_syncing(True)
    try:
        today: date = deps.today_fn()
        start = today - timedelta(days=WINDOW_PAST_DAYS)
        end = today + timedelta(days=WINDOW_FUTURE_DAYS + 1)

        # --- (a) 持鎖：只做本機設定快照/註冊，不碰網路 ---
        with settings_lock:
            accounts = load_accounts(config.accounts_dir())
            emails = {a["email"] for a in accounts}
            for known in list(state.snapshot().statuses):
                if known not in emails:
                    state.drop_account(known)
            changed = False
            plan: list[tuple[dict, list[str]]] = []
            for acc in accounts:
                email = acc["email"]
                cfg_acc = settings.ensure_account(email)
                if not cfg_acc.calendars:
                    for cal in acc.get("calendars", []):
                        cfg_acc.calendars[cal["id"]] = bool(cal.get("primary"))
                    changed = True
                enabled_ids = [cid for cid, enabled in cfg_acc.calendars.items() if enabled]
                plan.append((acc, enabled_ids))
            if changed:
                config.save_settings(settings)

        # --- (b) 不持鎖：網路階段（token 刷新＋抓事件＋normalize） ---
        for acc, enabled_ids in plan:
            email = acc["email"]
            try:
                tok = _get_token(acc, http_post=deps.http_post)
                events = []
                for cal_id in enabled_ids:
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

        # --- (c) 無需 settings 鎖；state 自己內部鎖住 ---
        state.save_cache()
    finally:
        state.set_syncing(False)


def weather_sync_once(state: AppState, settings, deps: SyncDeps,
                      settings_lock: threading.Lock | None = None) -> None:
    """天氣同步不碰 settings.accounts，理論上完全不需要鎖；
    但為求嚴謹，仍在鎖內快照 lat/lon/label 這幾個純量再放鎖去打網路。"""
    if settings_lock is not None:
        with settings_lock:
            lat, lon, label = settings.weather_lat, settings.weather_lon, settings.weather_label
    else:
        lat, lon, label = settings.weather_lat, settings.weather_lon, settings.weather_label
    try:
        w = fetch_weather(lat, lon, label, http_get=deps.http_get, now_fn=deps.now_fn)
        state.set_weather(w)
    except Exception:
        pass  # 保留舊值，UI 顯示資料年齡


def start_threads(state: AppState, settings, settings_lock: threading.Lock) -> None:
    deps = default_deps()

    def cal_loop():
        # calendar_sync_once 自己只在 phase (a) 短暫持鎖，這裡不再外包一層鎖，
        # 否則巢狀取鎖同一把非重入 Lock 會直接死結。
        calendar_sync_once(state, settings, deps, settings_lock)
        elapsed = 0
        while True:
            _time.sleep(1)
            elapsed += 1
            with settings_lock:
                interval_s = settings.sync_interval_min * 60
            if FORCE_CAL.is_set() or elapsed >= interval_s:
                FORCE_CAL.clear()
                elapsed = 0
                calendar_sync_once(state, settings, deps, settings_lock)

    def wx_loop():
        weather_sync_once(state, settings, deps, settings_lock)
        elapsed = 0
        while True:
            _time.sleep(1)
            elapsed += 1
            if FORCE_WX.is_set() or elapsed >= WX_INTERVAL:
                FORCE_WX.clear()
                elapsed = 0
                weather_sync_once(state, settings, deps, settings_lock)

    threading.Thread(target=cal_loop, daemon=True).start()
    threading.Thread(target=wx_loop, daemon=True).start()
