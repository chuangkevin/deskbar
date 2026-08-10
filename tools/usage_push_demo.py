"""Mac 端抓取 Claude Code / Antigravity / OpenAI usage 並可靠推送到 deskbar。

常駐迴圈刻意分開「抓新資料」與「補送快取」：Anthropic 最多每五分鐘抓一次，
本機有時間戳的快照每分鐘補送到 deskbar。這能在 Pi 重開後恢復 widget，
又不會把快取偽裝成新鮮資料；HTTP 429 以指數退避處理。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
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
    from tools.openai_usage import fetch_usage as fetch_openai_usage
except ImportError:
    try:
        from openai_usage import fetch_usage as fetch_openai_usage
    except ImportError:
        try:
            from .openai_usage import fetch_usage as fetch_openai_usage
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
CACHE_PATH = Path.home() / ".deskbar-agent" / "usage_cache.json"
# 2026-08-10 委派主力從 OpenCode 換成 Codex CLI；只看 opencode.db 會使
# 活動觸發永遠不發生，因此同時觀察 Codex 會更新的憑證與歷程檔。
OA_ACTIVITY_PATHS = (
    "~/.codex/auth.json",
    "~/.codex/history.jsonl",
    "~/.local/share/opencode/opencode.db",
)
DEFAULT_FETCH_INTERVAL = 300.0
DEFAULT_PUSH_INTERVAL = 60.0
DEFAULT_AG_INTERVAL = 300.0
DEFAULT_OA_INTERVAL = 3600.0
OA_MIN_INTERVAL = 300.0
INITIAL_RATE_LIMIT_BACKOFF = 900.0
MAX_RATE_LIMIT_BACKOFF = 3600.0

_AG_LOCK = threading.Lock()
_AG_FETCHING_LOCK = threading.Lock()
_AG_FETCHING = False
_AG_LATEST: dict = {
    "ag_5h_pct": None,
    "ag_5h_resets_at": None,
    "ag_weekly_pct": None,
    "ag_weekly_resets_at": None,
}

_OA_LOCK = threading.Lock()
_OA_FETCHING_LOCK = threading.Lock()
_OA_FETCHING = False
_OA_LAST_REFRESH_MONO: float | None = None
_OA_LAST_ACTIVITY_MTIME: float | None = None
_OA_ACTIVITY_MTIME_READY = False
_OA_LATEST: dict = {
    "oa_weekly_pct": None,
    "oa_weekly_resets_at": None,
}


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
    with _AG_LOCK:
        _AG_LATEST.update(fields)


def _ag_worker() -> None:
    global _AG_FETCHING
    try:
        if fetch_usage_text is None or parse_usage_panel is None:
            return
        text = fetch_usage_text()
        if not text:
            print("[Antigravity] 抓取文字為空，保留上一次用量資料")
            return
        parsed = parse_usage_panel(text)
        if not parsed or not any(v is not None for v in parsed.values()):
            print("[Antigravity] 解析結果全空，保留上一次用量資料")
            return
        now = datetime.now().astimezone()
        fields = ag_payload_fields(parsed, now)
        with _AG_LOCK:
            _AG_LATEST.update(fields)
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


def oa_payload_fields(parsed: dict | None, now: datetime) -> dict:
    """純函數：將 OpenAI header 解析結果換算為 deskbar payload 欄位。"""
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

    return {
        "oa_weekly_pct": pct,
        "oa_weekly_resets_at": resets_at,
    }


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
    fields = {
        "oa_weekly_pct": cached.get("oa_weekly_pct"),
        "oa_weekly_resets_at": cached.get("oa_weekly_resets_at"),
    }
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
        fields = oa_payload_fields(parsed, datetime.now().astimezone())
        if not any(v is not None for v in fields.values()):
            print("[OpenAI] 解析結果全空，保留上一次用量資料")
            return
        with _OA_LOCK:
            _OA_LATEST.update(fields)
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


def _latest_oa_activity_mtime(paths=OA_ACTIVITY_PATHS) -> float | None:
    """回傳存在活動檔的最新 mtime；缺檔不該中斷常駐推送。"""
    mtimes = []
    for path in paths:
        try:
            mtimes.append(Path(path).expanduser().stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else None


def _oa_activity_mtime_changed(paths=OA_ACTIVITY_PATHS) -> bool:
    """只有最新活動時間比已記錄值新時才推測剛消耗過 OpenAI 額度。"""
    global _OA_LAST_ACTIVITY_MTIME, _OA_ACTIVITY_MTIME_READY
    current = _latest_oa_activity_mtime(paths)

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
                  enable_openai: bool = True) -> dict:
    five_hour = usage.get("five_hour") or {}
    seven_day = usage.get("seven_day") or {}
    fable_pct, fable_resets_at = None, None
    for limit in usage.get("limits") or []:
        if limit.get("kind") == "weekly_scoped":
            fable_pct = limit.get("percent")
            fable_resets_at = limit.get("resets_at")
            break
    payload = {
        "session_pct": five_hour.get("utilization"),
        "session_resets_at": five_hour.get("resets_at"),
        "weekly_pct": seven_day.get("utilization"),
        "weekly_resets_at": seven_day.get("resets_at"),
        "fable_pct": fable_pct,
        "fable_resets_at": fable_resets_at,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if enable_antigravity:
        payload.update(get_antigravity_fields())
    if enable_openai and fetch_openai_usage is not None:
        payload.update(get_openai_fields())
    return payload


def load_cache(path: Path = CACHE_PATH) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def save_cache(payload: dict, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    if "oa_weekly_pct" in payload:
        summary += f"  OpenAI 週 {payload.get('oa_weekly_pct')}%"
    return summary


def one_cycle(
    url: str, token: str | None, enable_antigravity: bool = True,
    enable_openai: bool = True
) -> dict:
    payload = build_payload(
        fetch_usage(load_access_token()),
        enable_antigravity=enable_antigravity,
        enable_openai=enable_openai,
    )
    save_cache(payload)
    push(payload, url, token)
    print(f"已抓取並推送：{_summary(payload)}")
    return payload


def run_loop(
    url: str,
    token: str | None,
    fetch_interval: float,
    push_interval: float,
    ag_interval: float = DEFAULT_AG_INTERVAL,
    oa_interval: float = DEFAULT_OA_INTERVAL,
    enable_antigravity: bool = True,
    enable_openai: bool = True,
) -> None:
    cached = load_cache()
    openai_available = enable_openai and fetch_openai_usage is not None
    if enable_antigravity:
        warm_ag_from_cache(cached)
    if openai_available:
        warm_openai_from_cache(cached)
    next_fetch = 0.0
    next_push = 0.0
    next_ag = 0.0
    next_oa = 0.0
    rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
    ag_status = (
        f"Antigravity {ag_interval:g} 秒"
        if (enable_antigravity and fetch_usage_text is not None)
        else "Antigravity 已關閉"
    )
    oa_status = (
        f"OpenAI {oa_interval:g} 秒 + 活動檔觸發"
        if openai_available
        else "OpenAI 已關閉"
    )
    print(
        f"常駐模式啟動（Anthropic {fetch_interval:g} 秒、deskbar {push_interval:g} 秒、{ag_status}、{oa_status}）"
    )
    while True:
        now = time.monotonic()

        if enable_antigravity and now >= next_ag:
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
        if cached is not None and now >= next_push:
            if enable_antigravity:
                cached.update(get_antigravity_fields())
            if openai_available:
                cached.update(get_openai_fields())
            try:
                push(cached, url, token)
                print(f"已補送快取：{_summary(cached)}")
            except SystemExit as error:
                print(f"快取推送失敗：{error}")
            next_push = now + push_interval

        now = time.monotonic()
        if now >= next_fetch:
            try:
                cached = one_cycle(
                    url, token, enable_antigravity=enable_antigravity,
                    enable_openai=openai_available,
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
        events = [next_fetch, next_push if cached is not None else next_fetch]
        if enable_antigravity:
            events.append(next_ag)
        if openai_available:
            events.append(next_oa)
        next_event = min(events)
        time.sleep(max(1.0, min(5.0, next_event - now)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="deskbar /api/usage 完整網址")
    parser.add_argument("--token", default=None, help="選填 X-Deskbar-Token")
    parser.add_argument("--loop", action="store_true", help="常駐可靠推送模式")
    parser.add_argument("--fetch-interval", type=float,
                        default=DEFAULT_FETCH_INTERVAL)
    parser.add_argument("--push-interval", type=float,
                        default=DEFAULT_PUSH_INTERVAL)
    parser.add_argument("--ag-interval", type=float,
                        default=DEFAULT_AG_INTERVAL)
    parser.add_argument("--no-antigravity", action="store_true",
                        help="停用 Antigravity 用量抓取")
    parser.add_argument("--no-openai", action="store_true",
                        help="停用 OpenAI 用量抓取")
    args = parser.parse_args()

    enable_ag = not args.no_antigravity
    enable_oa = not args.no_openai

    if args.loop:
        run_loop(
            args.url,
            args.token,
            args.fetch_interval,
            args.push_interval,
            ag_interval=args.ag_interval,
            enable_antigravity=enable_ag,
            enable_openai=enable_oa,
        )
    else:
        one_cycle(args.url, args.token, enable_antigravity=enable_ag,
                  enable_openai=enable_oa)


if __name__ == "__main__":
    main()
