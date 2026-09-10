"""Mac 端抓取 Claude Code / Antigravity / OpenAI usage 並可靠推送到 deskbar。

常駐迴圈刻意分開「抓新資料」與「補送快取」：Anthropic 最多每五分鐘抓一次，
本機有時間戳的快照每分鐘補送到 deskbar。這能在 Pi 重開後恢復 widget，
又不會把快取偽裝成新鮮資料；HTTP 429 以指數退避處理。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

try:
    from tools.antigravity_usage import fetch_usage_text, parse_usage_panel
except ImportError:
    try:
        from antigravity_usage import fetch_usage_text, parse_usage_panel
    except ImportError:
        try:
            from .antigravity_usage import fetch_usage_text, parse_usage_panel
        except ImportError:
            fetch_usage_text = None
            parse_usage_panel = None

try:
    from tools.cursor_usage import fetch_usage as fetch_cursor_usage
except ImportError:
    try:
        from cursor_usage import fetch_usage as fetch_cursor_usage
    except ImportError:
        try:
            from .cursor_usage import fetch_usage as fetch_cursor_usage
        except ImportError:
            fetch_cursor_usage = None

try:
    from tools.openai_usage import fetch_all_usage as fetch_openai_usage
except ImportError:
    try:
        from openai_usage import fetch_all_usage as fetch_openai_usage
    except ImportError:
        try:
            from .openai_usage import fetch_all_usage as fetch_openai_usage
        except ImportError:
            fetch_openai_usage = None

CLAUDE_BIN = os.environ.get(
    "DESKBAR_CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude")
)
REFRESH_COOLDOWN_S = 600.0  # 兩次觸發換發之間至少間隔 10 分鐘
KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_cache_path_override = os.environ.get("DESKBAR_USAGE_CACHE")
CACHE_PATH = (
    Path(_cache_path_override).expanduser()
    if _cache_path_override
    else Path.home() / ".deskbar-agent" / "usage_cache.json"
)
# 2026-08-10 委派主力從 OpenCode 換成 Codex CLI；只看 opencode.db 會使
# 活動觸發永遠不發生，因此同時觀察 Codex 會更新的憑證與歷程檔。
OA_ACTIVITY_PATHS = (
    "~/.codex/auth.json",
    "~/.codex/history.jsonl",
    "~/.local/share/opencode/opencode.db",
)
OA_ACTIVITY_GLOB_PATTERNS = (
    "~/.codex/logs_*.sqlite-wal",
    "~/.codex/thread_history_*.sqlite-wal",
    "~/.codex/queue_*.sqlite-wal",
    "~/.codex/state_*.sqlite-wal",
)
DEFAULT_FETCH_INTERVAL = 300.0
DEFAULT_PUSH_INTERVAL = 60.0
DEFAULT_AG_INTERVAL = 300.0
# 2026-09-10 Kevin：一小時太久。OpenAI 每次刷新是一個真的 Codex 請求（會吃一點額度），
# 但那是「reply with just: ok」等級的極小請求；額度用完時更是連請求都沒送出就 429。
# Cursor 是純唯讀 GET，完全不花額度。兩者都拉到 5 分鐘，跟 Claude／Antigravity 一致，
# 順便讓 usagewidget 的「(N 分前)」不再常駐（那個門檻是 300 秒）。
DEFAULT_OA_INTERVAL = 300.0
DEFAULT_CU_INTERVAL = 300.0
DEFAULT_PREFS_INTERVAL = 60.0
DEFAULT_DESKBAR_USAGE_URL = "https://desk.sisihome.org/api/usage"
OA_MIN_INTERVAL = 120.0
CU_MIN_INTERVAL = 120.0
INITIAL_RATE_LIMIT_BACKOFF = 900.0
MAX_RATE_LIMIT_BACKOFF = 3600.0
# 與 deskbar.config.VALID_USAGE_SOURCES 對齊；publisher 刻意不 import deskbar。
VALID_USAGE_SOURCES = ("claude", "antigravity", "openai", "cursor")
# /api/prefs 讀不到且無本機確認過的清單時，不要預設打開 Claude（避免已退訂仍打 Anthropic）。
SAFE_BOOTSTRAP_USAGE_SOURCES = ("antigravity", "openai")
DEFAULT_USAGE_SOURCES = SAFE_BOOTSTRAP_USAGE_SOURCES
USAGE_SOURCES_CACHE_KEY = "usage_sources"

_AG_LOCK = threading.Lock()
_AG_FETCHING_LOCK = threading.Lock()
_AG_FETCHING = False
_AG_LATEST: dict = {
    "ag_5h_pct": None,
    "ag_5h_resets_at": None,
    "ag_weekly_pct": None,
    "ag_weekly_resets_at": None,
}

_CU_LOCK = threading.Lock()
_CU_FETCHING_LOCK = threading.Lock()
_CU_FETCHING = False
_CU_LAST_REFRESH_MONO: float | None = None
_CU_LATEST: dict = {
    "cu_pct": None,
    "cu_resets_at": None,
}


def cu_payload_fields(parsed: dict | None, now: datetime) -> dict:
    """純函數：把 cursor_usage 的解析結果換算成 deskbar payload 欄位。"""
    if not isinstance(parsed, dict):
        parsed = {}
    raw_pct = parsed.get("used_pct")
    if raw_pct is None or isinstance(raw_pct, bool):
        pct = None
    else:
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError):
            pct = None
    if pct is not None and not 0 <= pct <= 100:
        pct = None
    resets_at = parsed.get("resets_at")
    if not isinstance(resets_at, str) or not resets_at:
        resets_at = None
    return {"cu_pct": pct, "cu_resets_at": resets_at}


def get_cursor_fields() -> dict:
    """持鎖回傳 _CU_LATEST 的複本。"""
    with _CU_LOCK:
        return dict(_CU_LATEST)


def warm_cursor_from_cache(cached: dict | None) -> None:
    """啟動時用快取預熱，避免右欄 CURSOR 區塊短暫消失。"""
    if not isinstance(cached, dict):
        return
    fields = {
        "cu_pct": cached.get("cu_pct"),
        "cu_resets_at": cached.get("cu_resets_at"),
    }
    if "cu_fetched_at" in cached:
        fields["cu_fetched_at"] = cached.get("cu_fetched_at")
    with _CU_LOCK:
        _CU_LATEST.update(fields)


def _cu_worker() -> None:
    global _CU_FETCHING
    try:
        if fetch_cursor_usage is None:
            return
        parsed = fetch_cursor_usage()
        if parsed is None:
            print("[Cursor] 抓取失敗，保留上一次用量資料")
            return
        now = datetime.now(timezone.utc).astimezone()
        fields = cu_payload_fields(parsed, now)
        if fields.get("cu_pct") is None:
            print("[Cursor] 解析結果全空，保留上一次用量資料")
            return
        fields["cu_fetched_at"] = now.isoformat()
        with _CU_LOCK:
            _CU_LATEST.update(fields)
        cached = load_cache() or {}
        cached.update(fields)
        try:
            save_cache(cached)
        except OSError as error:
            print(f"[Cursor] 快取寫入失敗：{error}")
    except Exception as error:
        print(f"[Cursor] 抓取時發生例外：{type(error).__name__}")
    finally:
        with _CU_FETCHING_LOCK:
            global _CU_FETCHING
            _CU_FETCHING = False


def refresh_cursor_async(min_interval: float = CU_MIN_INTERVAL) -> threading.Thread | None:
    """背景刷新 Cursor 用量，最小間隔擋連發。"""
    global _CU_FETCHING, _CU_LAST_REFRESH_MONO
    if fetch_cursor_usage is None:
        return None
    now_mono = time.monotonic()
    with _CU_FETCHING_LOCK:
        if _CU_FETCHING:
            return None
        if (_CU_LAST_REFRESH_MONO is not None
                and now_mono - _CU_LAST_REFRESH_MONO < min_interval):
            return None
        _CU_FETCHING = True
        _CU_LAST_REFRESH_MONO = now_mono
    thread = threading.Thread(target=_cu_worker, daemon=True)
    thread.start()
    return thread


_OA_LOCK = threading.Lock()
_OA_FETCHING_LOCK = threading.Lock()
_OA_FETCHING = False
_OA_LAST_REFRESH_MONO: float | None = None
_OA_LAST_ACTIVITY_MTIME: float | None = None
_OA_ACTIVITY_MTIME_READY = False
_OA_LATEST: dict = {
    "oa_accounts": [],
    "oa_weekly_pct": None,
    "oa_weekly_resets_at": None,
    "oa_account_id": None,
    "oa_fetched_at": None,
}

# 背景 AG/OA 成功刷新後喚醒 run_loop，立刻補送新時間戳（不必等 push_interval）。
_SOURCE_REFRESH_EVENT = threading.Event()
# 供 _loop_idle_wait 辨識 time.sleep 是否被單元測試 monkeypatch。
_REAL_TIME_SLEEP = time.sleep
# 本機用量快取讀／合併／寫入臨界區；避免多 writer 共用固定 .tmp 互踩。
_CACHE_LOCK = threading.RLock()


def _notify_source_refresh_ready() -> None:
    """成功寫入記憶體＋磁碟後才呼叫；失敗／逾時／無效結果不得觸發。"""
    _SOURCE_REFRESH_EVENT.set()


def _consume_source_refresh_signal() -> bool:
    """若有待處理的成功刷新訊號則清除並回 True（避免 busy loop）。"""
    if not _SOURCE_REFRESH_EVENT.is_set():
        return False
    _SOURCE_REFRESH_EVENT.clear()
    return True


def _loop_idle_wait(timeout: float) -> None:
    """等待下一輪；可被來源刷新訊號中斷。

    生產路徑用 ``Event.wait``。若 ``time.sleep`` 被測試 monkeypatch，改走
    一次 sleep，保留既有 run_loop 測試以 sleep hook 停迴圈的方式。
    """
    if timeout < 0:
        timeout = 0.0
    if time.sleep is not _REAL_TIME_SLEEP:
        time.sleep(timeout)
        return
    _SOURCE_REFRESH_EVENT.wait(timeout=timeout)


def ag_payload_fields(parsed: dict | None, now: datetime) -> dict:
    """純函數：將 parse_usage_panel 輸出換算為 deskbar payload 欄位。"""
    if not parsed or not isinstance(parsed, dict):
        parsed = {}

    rem_5h = parsed.get("gemini_5h_remaining")
    ref_5h = parsed.get("gemini_5h_refresh_min")
    rem_wk = parsed.get("gemini_weekly_remaining")
    ref_wk = parsed.get("gemini_weekly_refresh_min")

    ag_5h_pct = (100 - rem_5h) if rem_5h is not None else None
    ag_weekly_pct = (100 - rem_wk) if rem_wk is not None else None

    ag_5h_resets_at = (
        (now + timedelta(minutes=ref_5h)).isoformat()
        if ref_5h is not None
        else None
    )
    ag_weekly_resets_at = (
        (now + timedelta(minutes=ref_wk)).isoformat()
        if ref_wk is not None
        else None
    )

    return {
        "ag_5h_pct": ag_5h_pct,
        "ag_5h_resets_at": ag_5h_resets_at,
        "ag_weekly_pct": ag_weekly_pct,
        "ag_weekly_resets_at": ag_weekly_resets_at,
    }


def _ag_pct_is_zero_or_missing(value) -> bool:
    if value is None:
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return True


def is_unusable_antigravity_fields(fields: dict | None) -> bool:
    """辨識「缺席／解析失敗」被當成成功的空結果。

    無效形狀：兩個百分比皆為 0 或缺失，且兩個重置時間皆缺失。
    真實 0% 若帶有重置時間戳則仍視為可用。
    """
    if not fields or not isinstance(fields, dict):
        return True
    pcts_empty = (
        _ag_pct_is_zero_or_missing(fields.get("ag_5h_pct"))
        and _ag_pct_is_zero_or_missing(fields.get("ag_weekly_pct"))
    )
    resets_missing = (
        fields.get("ag_5h_resets_at") is None
        and fields.get("ag_weekly_resets_at") is None
    )
    return pcts_empty and resets_missing


def get_antigravity_fields() -> dict:
    """持鎖回傳 _AG_LATEST 的複本。"""
    with _AG_LOCK:
        return dict(_AG_LATEST)


def warm_ag_from_cache(cached: dict | None) -> None:
    """啟動時用快取資料預熱 `_AG_LATEST`。

    快取裡的 Antigravity 用量資料是「上一輪」的，且 `ag_*_resets_at` 是固定的
    時間字串（若過期 deskbar 端的倒數會顯示「即將重置」）。
    但這樣做能避免重啟後在第一輪抓取完成前的 ~47 秒內 Antigravity 區塊完全空白、
    造成 deskbar UI 整區消失再出現的閃爍。寧可先顯示可能略舊的值，也不要讓整區閃爍。
    """
    if not cached or not isinstance(cached, dict):
        return
    fields = {
        "ag_5h_pct": cached.get("ag_5h_pct"),
        "ag_5h_resets_at": cached.get("ag_5h_resets_at"),
        "ag_weekly_pct": cached.get("ag_weekly_pct"),
        "ag_weekly_resets_at": cached.get("ag_weekly_resets_at"),
    }
    if "ag_fetched_at" in cached:
        fields["ag_fetched_at"] = cached.get("ag_fetched_at")
    with _AG_LOCK:
        _AG_LATEST.update(fields)


def _ag_worker() -> None:
    global _AG_FETCHING
    try:
        if fetch_usage_text is None or parse_usage_panel is None:
            return
        try:
            text = fetch_usage_text()
        except TimeoutError as error:
            # 逾時：不更新 ag_fetched_at、不覆寫記憶體／快取；single-flight 由 finally 釋放。
            print(f"[Antigravity] 抓取逾時：{error}，保留上一次用量資料")
            return
        if not text:
            print("[Antigravity] 抓取文字為空，保留上一次用量資料")
            return
        parsed = parse_usage_panel(text)
        if not parsed or not any(v is not None for v in parsed.values()):
            print("[Antigravity] 解析結果全空，保留上一次用量資料")
            return
        now = datetime.now().astimezone()
        fields = ag_payload_fields(parsed, now)
        if is_unusable_antigravity_fields(fields):
            print(
                "[Antigravity] 抓取結果無效（全 0% 且無重置時間），"
                "保留上一次用量資料"
            )
            return
        fields["ag_fetched_at"] = now.isoformat()
        with _AG_LOCK:
            _AG_LATEST.update(fields)
        try:
            merge_source_fields_into_cache(fields)
        except Exception as error:
            print(f"[Antigravity] 快取寫入失敗：{error}")
        else:
            _notify_source_refresh_ready()
    except Exception as error:
        print(f"[Antigravity] 抓取時發生例外：{error}")
    finally:
        with _AG_FETCHING_LOCK:
            global _AG_FETCHING
            _AG_FETCHING = False


def refresh_antigravity_async() -> threading.Thread | None:
    """在背景執行緒異步刷新 Antigravity 用量。若已有抓取在跑則直接略過。"""
    global _AG_FETCHING
    if fetch_usage_text is None or parse_usage_panel is None:
        return None
    with _AG_FETCHING_LOCK:
        if _AG_FETCHING:
            return None
        _AG_FETCHING = True

    thread = threading.Thread(target=_ag_worker, daemon=True)
    thread.start()
    return thread


def _oa_single_payload_fields(parsed: dict | None, now: datetime) -> dict:
    if not parsed or not isinstance(parsed, dict):
        parsed = {}

    raw_pct = parsed.get("used_pct")
    if raw_pct is None or isinstance(raw_pct, bool):
        pct = None
    else:
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError):
            pct = None

    raw_epoch = parsed.get("resets_at_epoch")
    resets_at = None
    if raw_epoch is not None and not isinstance(raw_epoch, bool):
        try:
            tz = now.tzinfo if now.tzinfo is not None else timezone.utc
            resets_at = datetime.fromtimestamp(int(raw_epoch), tz=timezone.utc).astimezone(tz).isoformat()
        except (OSError, OverflowError, TypeError, ValueError):
            resets_at = None

    fields = {
        "oa_weekly_pct": pct,
        "oa_weekly_resets_at": resets_at,
    }
    if "account_id" in parsed:
        fields["oa_account_id"] = parsed.get("account_id")
    if "fetched_at" in parsed:
        fields["oa_fetched_at"] = parsed.get("fetched_at")
    return fields


def _oa_legacy_fields_from_accounts(accounts: list) -> dict:
    fields = {
        "oa_weekly_pct": None,
        "oa_weekly_resets_at": None,
        "oa_account_id": None,
        "oa_fetched_at": None,
    }
    if not accounts:
        return fields
    first = accounts[0] if isinstance(accounts[0], dict) else {}
    fields["oa_weekly_pct"] = first.get("weekly_pct")
    fields["oa_weekly_resets_at"] = first.get("weekly_resets_at")
    fields["oa_account_id"] = first.get("account_id")
    fields["oa_fetched_at"] = first.get("fetched_at")
    return fields


def oa_payload_fields(parsed: dict | list | None, now: datetime) -> dict:
    """純函數：將 OpenAI header 解析結果換算為 deskbar payload 欄位。"""
    if isinstance(parsed, list):
        fetched_at = now.isoformat()
        accounts = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            single = _oa_single_payload_fields(item, now)
            accounts.append({
                "account_id": item.get("account_id"),
                "name": item.get("name"),
                "weekly_pct": single.get("oa_weekly_pct"),
                "weekly_resets_at": single.get("oa_weekly_resets_at"),
                "fetched_at": fetched_at,
            })
        fields = {"oa_accounts": accounts}
        fields.update(_oa_legacy_fields_from_accounts(accounts))
        return fields

    return _oa_single_payload_fields(parsed, now)


def _merge_oa_accounts(existing_accounts, fresh_accounts) -> list:
    accounts = [
        dict(account)
        for account in existing_accounts or []
        if isinstance(account, dict)
    ]
    account_index = {
        account.get("account_id"): index
        for index, account in enumerate(accounts)
        if account.get("account_id") is not None
    }
    for fresh in fresh_accounts or []:
        if not isinstance(fresh, dict):
            continue
        account_id = fresh.get("account_id")
        if account_id in account_index:
            accounts[account_index[account_id]] = dict(fresh)
        else:
            account_index[account_id] = len(accounts)
            accounts.append(dict(fresh))
    return accounts


def _merge_openai_fields(existing: dict, fresh: dict) -> dict:
    fresh_accounts = fresh.get("oa_accounts")
    if not isinstance(fresh_accounts, list):
        return fresh
    accounts = _merge_oa_accounts(existing.get("oa_accounts"), fresh_accounts)
    fields = dict(fresh)
    fields["oa_accounts"] = accounts
    fields.update(_oa_legacy_fields_from_accounts(accounts))
    return fields


def _has_usable_openai_fields(fields: dict | None) -> bool:
    if not fields or not isinstance(fields, dict):
        return False
    accounts = fields.get("oa_accounts")
    if isinstance(accounts, list):
        return any(
            isinstance(account, dict)
            and (
                account.get("weekly_pct") is not None
                or account.get("weekly_resets_at") is not None
            )
            for account in accounts
        )
    return (
        fields.get("oa_weekly_pct") is not None
        or fields.get("oa_weekly_resets_at") is not None
    )


def get_openai_fields() -> dict:
    """持鎖回傳 _OA_LATEST 的複本。"""
    with _OA_LOCK:
        return dict(_OA_LATEST)


def warm_openai_from_cache(cached: dict | None) -> None:
    """啟動時用快取資料預熱 OpenAI 用量。

    2026-08-10 實機驗證顯示每次 OpenAI 抓取都會消耗一點額度；啟動後先用上次
    成功 payload 避免右欄 OPENAI 區塊短暫消失，再讓低頻刷新慢慢補上新資料。
    """
    if not cached or not isinstance(cached, dict):
        return
    cached_accounts = cached.get("oa_accounts")
    fields = {
        "oa_accounts": cached_accounts if isinstance(cached_accounts, list) else [],
        "oa_weekly_pct": cached.get("oa_weekly_pct"),
        "oa_weekly_resets_at": cached.get("oa_weekly_resets_at"),
        "oa_account_id": cached.get("oa_account_id"),
    }
    if "oa_fetched_at" in cached:
        fields["oa_fetched_at"] = cached.get("oa_fetched_at")
    with _OA_LOCK:
        _OA_LATEST.update(fields)


def _oa_worker() -> None:
    global _OA_FETCHING
    try:
        if fetch_openai_usage is None:
            return
        parsed = fetch_openai_usage()
        if not parsed:
            print("[OpenAI] 抓取失敗，保留上一次用量資料")
            return
        if isinstance(parsed, dict):
            parsed = [parsed]
        now = datetime.now().astimezone()
        fresh_fields = oa_payload_fields(parsed, now)
        if not _has_usable_openai_fields(fresh_fields):
            print("[OpenAI] 解析結果全空，保留上一次用量資料")
            return
        with _OA_LOCK:
            fields = _merge_openai_fields(dict(_OA_LATEST), fresh_fields)
            _OA_LATEST.update(fields)
        try:
            merge_source_fields_into_cache(fields)
        except Exception as error:
            print(f"[OpenAI] 快取寫入失敗：{error}")
        else:
            _notify_source_refresh_ready()
    except Exception as error:
        print(f"[OpenAI] 抓取時發生例外：{error}")
    finally:
        with _OA_FETCHING_LOCK:
            _OA_FETCHING = False


def refresh_openai_async(min_interval: float = OA_MIN_INTERVAL) -> threading.Thread | None:
    """在背景執行緒異步刷新 OpenAI 用量，並用共用最小間隔避免連續消耗額度。"""
    global _OA_FETCHING, _OA_LAST_REFRESH_MONO
    if fetch_openai_usage is None:
        return None
    now = time.monotonic()
    with _OA_FETCHING_LOCK:
        if _OA_FETCHING:
            return None
        if _OA_LAST_REFRESH_MONO is not None and now - _OA_LAST_REFRESH_MONO < min_interval:
            return None
        _OA_FETCHING = True
        _OA_LAST_REFRESH_MONO = now

    thread = threading.Thread(target=_oa_worker, daemon=True)
    thread.start()
    return thread


_DEFAULT_OA_ACTIVITY_GLOBS = object()


def _iter_oa_activity_paths(
    paths=OA_ACTIVITY_PATHS,
    glob_patterns=_DEFAULT_OA_ACTIVITY_GLOBS,
):
    """Yield explicit legacy paths plus dynamic Codex WAL artifacts."""
    for path in paths:
        yield Path(path).expanduser()

    if glob_patterns is _DEFAULT_OA_ACTIVITY_GLOBS:
        glob_patterns = OA_ACTIVITY_GLOB_PATTERNS

    for pattern in glob_patterns:
        try:
            matches = glob.iglob(os.path.expanduser(str(pattern)))
            for match in matches:
                yield Path(match)
        except OSError:
            continue


def _latest_oa_activity_mtime(
    paths=OA_ACTIVITY_PATHS,
    glob_patterns=_DEFAULT_OA_ACTIVITY_GLOBS,
) -> float | None:
    """回傳存在活動檔的最新 mtime；缺檔不該中斷常駐推送。"""
    mtimes = []
    for path in _iter_oa_activity_paths(paths, glob_patterns):
        try:
            if not path.is_file():
                continue
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else None


def _oa_activity_mtime_changed(
    paths=OA_ACTIVITY_PATHS,
    glob_patterns=_DEFAULT_OA_ACTIVITY_GLOBS,
) -> bool:
    """只有最新活動時間比已記錄值新時才推測剛消耗過 OpenAI 額度。"""
    global _OA_LAST_ACTIVITY_MTIME, _OA_ACTIVITY_MTIME_READY
    current = _latest_oa_activity_mtime(paths, glob_patterns)

    if not _OA_ACTIVITY_MTIME_READY:
        _OA_LAST_ACTIVITY_MTIME = current
        _OA_ACTIVITY_MTIME_READY = True
        return False
    if current is not None and (
        _OA_LAST_ACTIVITY_MTIME is None or current > _OA_LAST_ACTIVITY_MTIME
    ):
        _OA_LAST_ACTIVITY_MTIME = current
        return True
    return False


class RateLimitedError(RuntimeError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Anthropic usage API rate limited")
        self.retry_after = retry_after


_last_refresh_time: float = 0.0


def trigger_token_refresh() -> bool:
    """呼叫 Claude Code CLI 觸發 Anthropic 官方 OAuth token 換發流程。

    根據 2026-08-05 實測，桌面版 Claude Code 不會將換發後的 accessToken
    寫回 macOS Keychain，導致常駐推送 agent 讀取 Keychain 時遇到 token 過期而中止。
    在終端機執行一次 `claude -p ...` 呼叫 CLI 官方流程，即可讓 Claude Code 自動換發
    新 token 並更新 Keychain 項目。

    此處刻意發出一次極小的 API 呼叫（-p ok --max-turns 1），目的不是取得回應，
    而是讓 Claude Code 走其官方 refresh 流程將新 token 寫回 Keychain。
    雖然會消耗極少量額度並輕微擾動量測數字，但相較於自行實作 OAuth 換發可能弄壞
    使用者登入狀態的風險，這是刻意採用的取捨。
    """
    global _last_refresh_time
    claude_path = Path(CLAUDE_BIN)
    if not claude_path.exists():
        print(f"[Claude Code] 找不到 claude CLI 執行檔：{CLAUDE_BIN}")
        return False

    now = time.time()
    if now - _last_refresh_time < REFRESH_COOLDOWN_S:
        return False

    _last_refresh_time = now

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "ok", "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except Exception:
        # 依規格需求，任何例外（FileNotFoundError / TimeoutExpired / OSError）皆吞掉回 False
        return False


def load_access_token(allow_refresh: bool = True) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"讀不到 Keychain 項目「{KEYCHAIN_SERVICE}」：{result.stderr.strip()}"
        )
    try:
        oauth = json.loads(result.stdout.strip()).get("claudeAiOauth", {})
    except json.JSONDecodeError as error:
        raise SystemExit(f"Keychain 內容不是預期的 JSON：{error}")
    token = oauth.get("accessToken")
    if not token:
        raise SystemExit("Keychain 資料裡沒有 accessToken 欄位")
    expires_at = oauth.get("expiresAt", 0)
    if expires_at and expires_at / 1000 < time.time():
        if allow_refresh and trigger_token_refresh():
            return load_access_token(allow_refresh=False)
        raise SystemExit(
            "token 已過期且自動換發失敗，請手動在終端機跑一次 claude"
        )
    return token


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def fetch_usage(token: str) -> dict:
    try:
        response = requests.get(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": USAGE_BETA_HEADER,
                "User-Agent": UA,
            },
            timeout=20,
        )
    except requests.RequestException as error:
        raise SystemExit(f"打 usage API 失敗：{error}")
    if response.status_code == 429:
        raise RateLimitedError(_retry_after(response))
    try:
        response.raise_for_status()
    except requests.RequestException as error:
        raise SystemExit(f"打 usage API 失敗：{error}")
    try:
        return response.json()
    except ValueError as error:
        raise SystemExit(f"usage API 回應不是合法 JSON：{error}")


def build_payload(usage: dict, enable_antigravity: bool = True,
                  enable_openai: bool = True,
                  enable_cursor: bool = False) -> dict:
    five_hour = usage.get("five_hour") or {}
    seven_day = usage.get("seven_day") or {}
    fable_pct, fable_resets_at = None, None
    for limit in usage.get("limits") or []:
        if limit.get("kind") == "weekly_scoped":
            fable_pct = limit.get("percent")
            fable_resets_at = limit.get("resets_at")
            break
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "session_pct": five_hour.get("utilization"),
        "session_resets_at": five_hour.get("resets_at"),
        "weekly_pct": seven_day.get("utilization"),
        "weekly_resets_at": seven_day.get("resets_at"),
        "fable_pct": fable_pct,
        "fable_resets_at": fable_resets_at,
        # Claude API 成功回應後才會走進 build_payload；因此此時間就是它真正
        # 的最後成功抓取時間。補送 cache 的路徑完全不會改它。
        "fetched_at": fetched_at,
        "claude_fetched_at": fetched_at,
    }
    if enable_antigravity:
        payload.update(get_antigravity_fields())
    if enable_openai and fetch_openai_usage is not None:
        payload.update(get_openai_fields())
    if enable_cursor and fetch_cursor_usage is not None:
        payload.update(get_cursor_fields())
    return payload


def load_cache(path: Path | None = None) -> dict | None:
    path = CACHE_PATH if path is None else path
    with _CACHE_LOCK:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None


def save_cache(payload: dict, path: Path | None = None) -> dict:
    """落地用量快取；若 payload 未帶 usage_sources，保留磁碟上既有的確認清單。

    持 ``_CACHE_LOCK`` 並以唯一暫存檔原子 replace，避免 AG/OA/主迴圈
    並行寫入時互踩固定 ``usage_cache.tmp``。
    """
    path = CACHE_PATH if path is None else path
    with _CACHE_LOCK:
        to_write = dict(payload)
        if USAGE_SOURCES_CACHE_KEY not in to_write:
            existing = load_cache(path)
            if existing and USAGE_SOURCES_CACHE_KEY in existing:
                to_write[USAGE_SOURCES_CACHE_KEY] = existing[USAGE_SOURCES_CACHE_KEY]
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f"{path.stem}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(to_write, ensure_ascii=False, sort_keys=True) + "\n"
                )
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return to_write


def cached_usage_sources(cached: dict | None) -> tuple[str, ...] | None:
    """從本機快取讀出上次成功確認的 usage_sources；無效則 None。"""
    if not cached or not isinstance(cached, dict):
        return None
    return normalize_remote_usage_sources(cached.get(USAGE_SOURCES_CACHE_KEY))


def bootstrap_usage_sources(cached: dict | None) -> tuple[str, ...]:
    """prefs 失敗時的啟動來源：已確認快取優先，否則安全預設（不含 Claude）。"""
    return cached_usage_sources(cached) or SAFE_BOOTSTRAP_USAGE_SOURCES


def persist_usage_sources(
    sources: tuple[str, ...], path: Path | None = None
) -> dict:
    """把正規化後的 usage_sources 寫進本機快取，不覆寫各 provider 百分比／時間戳。"""
    path = CACHE_PATH if path is None else path
    with _CACHE_LOCK:
        cached = load_cache(path)
        if cached is None:
            cached = {}
        else:
            cached = dict(cached)
        cached[USAGE_SOURCES_CACHE_KEY] = list(sources)
        return save_cache(cached, path)


def merge_source_fields_into_cache(
    fields: dict, path: Path | None = None
) -> dict | None:
    """把單一來源成功抓到的欄位合併進本機快取並落地。

    Claude 403/429 時只會走快取補送；若 AG/OA 剛刷新卻沒寫回 cache，
    重啟或後續 replay 會丟掉 ``ag_fetched_at`` / ``oa_fetched_at``。
    沒有既有快取（從未成功抓過 Claude）時不新建——補送路徑本來就需要它。
    整段 load／merge／write 在 ``_CACHE_LOCK`` 內，避免並行來源互相覆寫。
    """
    path = CACHE_PATH if path is None else path
    if not fields or not isinstance(fields, dict):
        return load_cache(path)
    with _CACHE_LOCK:
        cached = load_cache(path)
        if cached is None:
            return None
        cached = dict(cached)
        cached.update(fields)
        save_cache(cached, path)
        return cached


def push(payload: dict, url: str, token: str | None) -> None:
    headers = {"X-Deskbar-Token": token} if token else {}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
    except requests.RequestException as error:
        raise SystemExit(f"推送到 deskbar 失敗：{error}")
    if response.status_code != 204:
        raise SystemExit(
            f"deskbar 回應非預期：HTTP {response.status_code} {response.text[:200]}"
        )


def prefs_url_from_usage_url(usage_url: str) -> str:
    """由 ``--url`` 的 /api/usage 推導 GET /api/prefs（讀 usage_sources）。"""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(usage_url)
    path = parts.path.rstrip("/") or ""
    if path.endswith("/api/usage"):
        new_path = f"{path[:-len('/api/usage')]}/api/prefs"
    elif path.endswith("/usage"):
        new_path = f"{path[:-len('/usage')]}/prefs"
    else:
        new_path = f"{path}/api/prefs" if path else "/api/prefs"
    if not new_path.startswith("/"):
        new_path = "/" + new_path
    return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))


def normalize_remote_usage_sources(value) -> tuple[str, ...] | None:
    """正規化 deskbar prefs 的 usage_sources；無法辨識時回 None。"""
    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
        return None
    if any(x not in VALID_USAGE_SOURCES for x in value):
        return None
    return tuple(key for key in VALID_USAGE_SOURCES if key in value)


def fetch_usage_sources(prefs_url: str, token: str | None = None) -> tuple[str, ...] | None:
    """GET /api/prefs，回傳正規化後的 usage_sources；失敗回 None（呼叫端沿用上次／預設）。"""
    headers = {"X-Deskbar-Token": token} if token else {}
    try:
        response = requests.get(prefs_url, headers=headers, timeout=5)
    except requests.RequestException as error:
        print(f"讀取 usage_sources 失敗：{error}")
        return None
    if response.status_code != 200:
        print(
            f"讀取 usage_sources 失敗：HTTP {response.status_code} "
            f"{response.text[:200]}"
        )
        return None
    try:
        data = response.json()
    except ValueError as error:
        print(f"讀取 usage_sources 失敗：回應不是合法 JSON：{error}")
        return None
    if not isinstance(data, dict):
        return None
    return normalize_remote_usage_sources(data.get("usage_sources"))


def resolve_enabled_sources(
    sources: tuple[str, ...],
    *,
    want_antigravity: bool = True,
    want_openai: bool = True,
) -> tuple[bool, bool, bool]:
    """回傳 (enable_claude, enable_antigravity, enable_openai)。

    CLI ``--no-*`` 只能再關、不能覆寫 prefs 把已關閉來源強制打開。
    """
    enable_claude = "claude" in sources
    enable_ag = want_antigravity and "antigravity" in sources
    enable_oa = want_openai and "openai" in sources and fetch_openai_usage is not None
    return enable_claude, enable_ag, enable_oa


def cursor_enabled(sources: tuple[str, ...], want_cursor: bool = True) -> bool:
    """Cursor 是否啟用。刻意不併進 resolve_enabled_sources，避免改動既有 3-tuple 簽章。"""
    return want_cursor and "cursor" in sources and fetch_cursor_usage is not None


def null_claude_payload() -> dict:
    """Claude 停用時的推送殼：不帶 stale fetched_at，避免擋 AG/OA 補送。"""
    return {
        "session_pct": None,
        "session_resets_at": None,
        "weekly_pct": None,
        "weekly_resets_at": None,
        "fable_pct": None,
        "fable_resets_at": None,
    }


def compose_publish_payload(
    cached: dict | None,
    *,
    enable_claude: bool,
    enable_antigravity: bool,
    enable_openai: bool,
    enable_cursor: bool = False,
) -> dict | None:
    """組出這一輪要推的 payload。

    Claude 停用時即使沒有本機 Claude 快取，只要 AG/OA 有資料仍可推送；
    也不會用舊的全域 ``fetched_at`` 當閘門。
    """
    used_null_shell = False
    if cached is not None:
        payload = dict(cached)
        # 本機 prefs 中繼資料不得進 POST /api/usage。
        payload.pop(USAGE_SOURCES_CACHE_KEY, None)
    else:
        payload = {}

    if not payload:
        if not enable_claude and (enable_antigravity or enable_openai or enable_cursor):
            payload = null_claude_payload()
            used_null_shell = True
        else:
            return None

    if not enable_claude:
        # 停用時不要讓舊 Claude 時間戳冒充「整包新鮮度」；分來源戳留給 AG/OA。
        payload.pop("fetched_at", None)
        payload.pop("claude_fetched_at", None)
        for key, value in null_claude_payload().items():
            payload[key] = value
    if enable_antigravity:
        payload.update(get_antigravity_fields())
    if enable_openai:
        payload.update(get_openai_fields())
    if enable_cursor:
        payload.update(get_cursor_fields())
    if used_null_shell:
        # 啟動當下 AG/OA 尚未抓到前，不要用全 None payload 洗掉 deskbar 既有畫面。
        interesting = []
        if enable_antigravity:
            interesting.extend(get_antigravity_fields().values())
        if enable_openai:
            oa_fields = get_openai_fields()
            accounts = oa_fields.get("oa_accounts")
            if isinstance(accounts, list):
                for account in accounts:
                    if isinstance(account, dict):
                        interesting.append(account.get("weekly_pct"))
                        interesting.append(account.get("weekly_resets_at"))
            else:
                interesting.extend(oa_fields.values())
        if enable_cursor:
            interesting.append(get_cursor_fields().get("cu_pct"))
        if not any(v is not None for v in interesting):
            return None
    return payload


def _summary(payload: dict) -> str:
    summary = (
        f"5h {payload.get('session_pct')}%  週 {payload.get('weekly_pct')}%  "
        f"fable {payload.get('fable_pct')}%"
    )
    if "ag_5h_pct" in payload:
        summary += (
            f"  AG 5h {payload.get('ag_5h_pct')}%  "
            f"AG 週 {payload.get('ag_weekly_pct')}%"
        )
    oa_accounts = payload.get("oa_accounts")
    if isinstance(oa_accounts, list) and oa_accounts:
        parts = []
        for account in oa_accounts:
            if not isinstance(account, dict):
                continue
            label = account.get("name") or str(account.get("account_id") or "")[:8]
            if not label:
                label = "unknown"
            parts.append(f"{label} {account.get('weekly_pct')}%")
        if parts:
            summary += f"  OpenAI {' / '.join(parts)}"
    elif "oa_weekly_pct" in payload:
        summary += f"  OpenAI 週 {payload.get('oa_weekly_pct')}%"
    if payload.get("cu_pct") is not None:
        summary += f"  Cursor {payload.get('cu_pct')}%"
    return summary


def one_cycle(
    url: str, token: str | None, enable_antigravity: bool = True,
    enable_openai: bool = True, enable_cursor: bool = False
) -> dict:
    payload = build_payload(
        fetch_usage(load_access_token()),
        enable_antigravity=enable_antigravity,
        enable_openai=enable_openai,
        enable_cursor=enable_cursor,
    )
    cached = save_cache(payload)
    push(payload, url, token)
    print(f"已抓取並推送：{_summary(payload)}")
    return cached


def run_loop(
    url: str,
    token: str | None,
    fetch_interval: float,
    push_interval: float,
    ag_interval: float = DEFAULT_AG_INTERVAL,
    oa_interval: float = DEFAULT_OA_INTERVAL,
    cu_interval: float = DEFAULT_CU_INTERVAL,
    enable_antigravity: bool = True,
    enable_openai: bool = True,
    enable_cursor: bool = True,
    prefs_interval: float = DEFAULT_PREFS_INTERVAL,
) -> None:
    prefs_url = prefs_url_from_usage_url(url)
    cached = load_cache()
    remote_sources = fetch_usage_sources(prefs_url, token)
    if remote_sources is None:
        remote_sources = bootstrap_usage_sources(cached)
        print(
            "usage_sources 讀取失敗，暫用 "
            f"{list(remote_sources)}；之後每 {prefs_interval:g} 秒重試"
        )
    else:
        print(f"deskbar usage_sources={list(remote_sources)}")
        cached = persist_usage_sources(remote_sources)

    enable_claude, enable_ag, openai_available = resolve_enabled_sources(
        remote_sources,
        want_antigravity=enable_antigravity,
        want_openai=enable_openai,
    )

    cursor_available = cursor_enabled(remote_sources, enable_cursor)

    if enable_ag:
        warm_ag_from_cache(cached)
    if openai_available:
        warm_openai_from_cache(cached)
    if cursor_available:
        warm_cursor_from_cache(cached)
    next_fetch = 0.0
    next_push = 0.0
    next_ag = 0.0
    next_oa = 0.0
    next_cu = 0.0
    next_prefs = time.monotonic() + prefs_interval
    rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
    claude_status = (
        f"Anthropic {fetch_interval:g} 秒" if enable_claude else "Claude 已關閉"
    )
    ag_status = (
        f"Antigravity {ag_interval:g} 秒"
        if (enable_ag and fetch_usage_text is not None)
        else "Antigravity 已關閉"
    )
    oa_status = (
        f"OpenAI {oa_interval:g} 秒 + 活動檔觸發"
        if openai_available
        else "OpenAI 已關閉"
    )
    cu_status = (
        f"Cursor {cu_interval:g} 秒" if cursor_available else "Cursor 已關閉"
    )
    print(
        f"常駐模式啟動（{claude_status}、deskbar {push_interval:g} 秒、"
        f"{ag_status}、{oa_status}、{cu_status}、prefs {prefs_interval:g} 秒）"
    )
    while True:
        now = time.monotonic()

        if now >= next_prefs:
            refreshed = fetch_usage_sources(prefs_url, token)
            if refreshed is not None:
                cached = persist_usage_sources(refreshed)
                if refreshed != remote_sources:
                    was_claude = enable_claude
                    remote_sources = refreshed
                    enable_claude, enable_ag, openai_available = resolve_enabled_sources(
                        remote_sources,
                        want_antigravity=enable_antigravity,
                        want_openai=enable_openai,
                    )
                    print(f"usage_sources 已更新為 {list(remote_sources)}")
                    if enable_claude and not was_claude:
                        next_fetch = 0.0
                        rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
                    if enable_ag:
                        warm_ag_from_cache(cached)
                    if openai_available:
                        warm_openai_from_cache(cached)
                    cursor_available = cursor_enabled(remote_sources, enable_cursor)
                    if cursor_available:
                        warm_cursor_from_cache(cached)
            next_prefs = now + prefs_interval

        if enable_ag and now >= next_ag:
            refresh_antigravity_async()
            next_ag = now + ag_interval

        now = time.monotonic()
        if openai_available:
            # 2026-08-10 實機驗證：OpenAI 用量只能靠真實請求 header 取得，
            # 每次刷新都消耗一點額度，所以平時不輪詢；只在剛用過 Codex CLI
            # 或距上次兜底刷新超過一小時時才嘗試，並由 OA_MIN_INTERVAL 擋連發。
            activity_changed = _oa_activity_mtime_changed()
            if now >= next_oa or activity_changed:
                started = refresh_openai_async()
                if started is not None:
                    next_oa = now + oa_interval
                elif now >= next_oa:
                    next_oa = now + min(OA_MIN_INTERVAL, oa_interval)

        now = time.monotonic()
        if cursor_available and now >= next_cu:
            started = refresh_cursor_async()
            if started is not None:
                next_cu = now + cu_interval
            else:
                next_cu = now + min(CU_MIN_INTERVAL, cu_interval)

        now = time.monotonic()
        # 背景 AG/OA 成功刷新：立刻排程補送，不必等到原本的 push_interval。
        if _consume_source_refresh_signal():
            next_push = now

        if now >= next_push:
            payload = compose_publish_payload(
                cached,
                enable_claude=enable_claude,
                enable_antigravity=enable_ag,
                enable_openai=openai_available,
                enable_cursor=cursor_available,
            )
            if payload is not None:
                # Claude 失敗或停用期間仍要把剛刷新的 AG/OA 時間戳寫回磁碟，
                # 讓後續 cache-replay / 重啟暖機帶得分來源新鮮度。
                cached = save_cache(payload)
                try:
                    push(payload, url, token)
                    print(f"已補送快取：{_summary(payload)}")
                except SystemExit as error:
                    print(f"快取推送失敗：{error}")
                next_push = now + push_interval

        now = time.monotonic()
        if enable_claude and now >= next_fetch:
            try:
                cached = one_cycle(
                    url, token, enable_antigravity=enable_ag,
                    enable_openai=openai_available,
                    enable_cursor=cursor_available,
                )
                next_fetch = now + fetch_interval
                next_push = now + push_interval
                rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
            except RateLimitedError as error:
                wait = max(rate_limit_backoff, error.retry_after or 0.0)
                next_fetch = now + wait
                rate_limit_backoff = min(
                    rate_limit_backoff * 2.0, MAX_RATE_LIMIT_BACKOFF
                )
                print(
                    f"Anthropic 429，{round(wait)} 秒後再抓；期間補送本機快取"
                )
            except SystemExit as error:
                next_fetch = now + fetch_interval
                print(f"抓取失敗：{error}；期間補送本機快取")

        now = time.monotonic()
        events = [next_prefs, next_push]
        if enable_claude:
            events.append(next_fetch)
        if enable_ag:
            events.append(next_ag)
        if openai_available:
            events.append(next_oa)
        if cursor_available:
            events.append(next_cu)
        next_event = min(events)
        # 可被 AG/OA 成功刷新訊號中斷，讓新鮮時間戳在下一輪立刻推送。
        _loop_idle_wait(max(1.0, min(5.0, next_event - now)))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_DESKBAR_USAGE_URL,
        help="deskbar /api/usage 完整網址",
    )
    parser.add_argument("--token", default=None, help="選填 X-Deskbar-Token")
    parser.add_argument("--loop", action="store_true", help="常駐可靠推送模式")
    parser.add_argument("--fetch-interval", type=float,
                        default=DEFAULT_FETCH_INTERVAL)
    parser.add_argument("--push-interval", type=float,
                        default=DEFAULT_PUSH_INTERVAL)
    parser.add_argument("--ag-interval", type=float,
                        default=DEFAULT_AG_INTERVAL)
    parser.add_argument("--oa-interval", type=float,
                        default=DEFAULT_OA_INTERVAL,
                        help="多久刷新一次 OpenAI 用量（每次會送一個極小的 Codex 請求）")
    parser.add_argument("--cu-interval", type=float,
                        default=DEFAULT_CU_INTERVAL,
                        help="多久刷新一次 Cursor 用量（唯讀 GET，不花額度）")
    parser.add_argument("--prefs-interval", type=float,
                        default=DEFAULT_PREFS_INTERVAL,
                        help="多久重讀一次 deskbar /api/prefs 的 usage_sources")
    parser.add_argument("--no-antigravity", action="store_true",
                        help="停用 Antigravity 用量抓取")
    parser.add_argument("--no-openai", action="store_true",
                        help="停用 OpenAI 用量抓取")
    parser.add_argument("--no-cursor", action="store_true",
                        help="停用 Cursor 用量抓取")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    enable_ag = not args.no_antigravity
    enable_oa = not args.no_openai
    enable_cu = not args.no_cursor

    if args.loop:
        run_loop(
            args.url,
            args.token,
            args.fetch_interval,
            args.push_interval,
            ag_interval=args.ag_interval,
            oa_interval=args.oa_interval,
            cu_interval=args.cu_interval,
            enable_antigravity=enable_ag,
            enable_openai=enable_oa,
            enable_cursor=enable_cu,
            prefs_interval=args.prefs_interval,
        )
    else:
        one_cycle(args.url, args.token, enable_antigravity=enable_ag,
                  enable_openai=enable_oa, enable_cursor=enable_cu)


if __name__ == "__main__":
    main()
