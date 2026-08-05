from __future__ import annotations

import sys
import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import requests

from deskbar import config
from deskbar.auth import AuthError, get_access_token, load_accounts
from deskbar.gcal import SyncError, fetch_range_events
from deskbar.models import normalize_event
from deskbar.store import AppState
from deskbar.weather import fetch_weather

CAL_INTERVAL, WX_INTERVAL = 300, 1800
# 失敗後快速重試的指數退避（秒）。Transient 網路/DNS 抖動通常幾秒到一兩分鐘就
# 恢復；若失敗一次就得等完整間隔（日曆 5–10 分、天氣 30 分），儀表板會一直掛著
# 「部分帳號同步異常」。退避序列：15s → 30s → 60s → 120s → 300s（封頂），
# 成功即重置回到正常間隔。300s 之後就跟正常間隔同量級，不再更快。
RETRY_DELAYS: Final = (15, 30, 60, 120, 300)
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


def _next_retry_elapsed(streak: int) -> int | None:
    """streak 次連續失敗後，下一次重試要等幾秒（None＝不縮短正常間隔）。"""
    if streak <= 0:
        return None
    return RETRY_DELAYS[min(streak - 1, len(RETRY_DELAYS) - 1)]


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
        ok_all = True
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
                ok_all = False
            except (SyncError, OSError, ValueError, KeyError, requests.RequestException):
                state.set_error(email, "同步失敗", deps.now_fn())
                ok_all = False

        # --- (c) 無需 settings 鎖；state 自己內部鎖住 ---
        state.save_cache()
        return ok_all
    finally:
        state.set_syncing(False)


def weather_sync_once(state: AppState, settings, deps: SyncDeps,
                      settings_lock: threading.Lock | None = None) -> None:
    """天氣同步不碰 settings.accounts，理論上完全不需要鎖；
    但為求嚴謹，仍在鎖內快照 lat/lon/label/metar_station 這幾個純量再放鎖去打網路。

    自動定位（weather_auto_locate，預設開）：每輪先用 IP 反查位置，跟目前
    設定差超過 ~5km（0.05°）或城市名變了才改寫並持久化——裝置搬到公司、
    換熱點，天氣自動跟著走；IP 查詢失敗就沿用原設定，不擋天氣本身。"""
    if settings_lock is not None:
        with settings_lock:
            auto = getattr(settings, "weather_auto_locate", True)
            lat, lon, label = settings.weather_lat, settings.weather_lon, settings.weather_label
            metar_station = getattr(settings, "weather_metar_station", "RCSS")
    else:
        auto = getattr(settings, "weather_auto_locate", True)
        lat, lon, label = settings.weather_lat, settings.weather_lon, settings.weather_label
        metar_station = getattr(settings, "weather_metar_station", "RCSS")
    if auto:
        from deskbar import config as _cfg
        from deskbar import geoloc
        loc = geoloc.locate(http_get=deps.http_get)
        if loc is not None:
            nlat, nlon, nlabel = loc
            if (abs(nlat - lat) > 0.05 or abs(nlon - lon) > 0.05
                    or (nlabel and nlabel != label)):
                lat, lon, label = nlat, nlon, nlabel
                try:
                    if settings_lock is not None:
                        with settings_lock:
                            settings.weather_lat, settings.weather_lon = nlat, nlon
                            settings.weather_label = nlabel
                            _cfg.save_settings(settings)
                    else:
                        settings.weather_lat, settings.weather_lon = nlat, nlon
                        settings.weather_label = nlabel
                        _cfg.save_settings(settings)
                except OSError as e:
                    print(f"[deskbar] geoloc save failed: {e}", file=sys.stderr)
    try:
        w = fetch_weather(lat, lon, label, http_get=deps.http_get, now_fn=deps.now_fn,
                          metar_station=metar_station)
        state.set_weather(w)
        return True
    except Exception as e:
        # 保留舊值，UI 顯示資料年齡（AppState 沒有天氣專屬的 last_error 欄位，
        # 這裡本來完全靜默、故障時無從得知原因——至少寫一行 stderr 供 journald 除錯。
        print(f"[deskbar] weather sync failed: {e}", file=sys.stderr)
        return False


LINEAR_INTERVAL = 300      # Linear 待辦輪詢間隔（秒）；唯讀查詢，5 分鐘足夠


def linear_sync_once(state: AppState, settings,
                     settings_lock: threading.Lock | None = None) -> None:
    """有設 API Key 才打；失敗保留舊資料＋stderr 一行（比照 weather）。"""
    from deskbar import linear as linear_mod
    if settings_lock is not None:
        with settings_lock:
            key = getattr(settings, "linear_api_key", "")
    else:
        key = getattr(settings, "linear_api_key", "")
    if not key:
        return True
    try:
        items = linear_mod.fetch_issues(key)
        at = datetime.now(ZoneInfo("Asia/Taipei"))
        state.set_linear(items, at)
        linear_mod.save_cache(items, at)
        return True
    except Exception as e:
        print(f"[deskbar] linear sync failed: {e}", file=sys.stderr)
        return False


def _try_once(fn, streak: int) -> int:
    """執行一次同步；回傳更新後的連續失敗次數（成功歸零，例外/False 累加）。"""
    try:
        ok = fn()
        return 0 if ok else streak + 1
    except Exception as e:
        print(f"[deskbar] {getattr(fn, '__name__', 'sync')} failed: {e}",
              file=sys.stderr)
        return streak + 1


def _sync_loop(fn, interval_getter, force_event: threading.Event | None):
    """帶指數退避重試的同步迴圈。

    失敗後不必等完整間隔：依連續失敗次數在 RETRY_DELAYS 退避（15→30→60→120→
    300s 封頂）快速重試，成功立刻重置回正常間隔。force_event 用 check-and-clear
    消費自己的事件（FORCE_CAL/FORCE_WX 各自獨立，不會互相誤清）。
    """
    def run():
        streak = _try_once(fn, 0)
        elapsed = 0
        while True:
            _time.sleep(1)
            elapsed += 1
            due = force_event is not None and force_event.is_set()
            due = due or elapsed >= interval_getter()
            retry_in = _next_retry_elapsed(streak)
            if retry_in is not None and elapsed >= retry_in:
                due = True
            if not due:
                continue
            if force_event is not None:
                force_event.clear()
            elapsed = 0
            streak = _try_once(fn, streak)
    return run


def start_threads(state: AppState, settings, settings_lock: threading.Lock) -> None:
    deps = default_deps()

    def cal_interval() -> int:
        with settings_lock:
            return settings.sync_interval_min * 60

    threading.Thread(target=_sync_loop(
        lambda: calendar_sync_once(state, settings, deps, settings_lock),
        cal_interval, FORCE_CAL), daemon=True, name="cal-sync").start()
    threading.Thread(target=_sync_loop(
        lambda: weather_sync_once(state, settings, deps, settings_lock),
        lambda: WX_INTERVAL, FORCE_WX), daemon=True, name="wx-sync").start()
    threading.Thread(target=_sync_loop(
        lambda: linear_sync_once(state, settings, settings_lock),
        lambda: LINEAR_INTERVAL, None), daemon=True, name="linear-sync").start()
