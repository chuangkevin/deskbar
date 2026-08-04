"""Fetch Claude Code usage on the Mac and reliably push it to deskbar.

The loop deliberately separates the two network jobs: Anthropic is queried at most every
five minutes, while the last timestamped snapshot is re-pushed to deskbar every minute.
This restores the widget after a Pi restart without hammering Anthropic or making cached
data look fresh. HTTP 429 responses use exponential backoff.
"""
from __future__ import annotations

import argparse
import json
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

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CACHE_PATH = Path.home() / ".deskbar-agent" / "usage_cache.json"
DEFAULT_FETCH_INTERVAL = 300.0
DEFAULT_PUSH_INTERVAL = 60.0
DEFAULT_AG_INTERVAL = 300.0
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


class RateLimitedError(RuntimeError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Anthropic usage API rate limited")
        self.retry_after = retry_after


def load_access_token() -> str:
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
        raise SystemExit("token 已過期，請執行一次 Claude Code 以刷新登入")
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


def build_payload(usage: dict, enable_antigravity: bool = True) -> dict:
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
    return summary


def one_cycle(
    url: str, token: str | None, enable_antigravity: bool = True
) -> dict:
    payload = build_payload(
        fetch_usage(load_access_token()),
        enable_antigravity=enable_antigravity,
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
    enable_antigravity: bool = True,
) -> None:
    cached = load_cache()
    next_fetch = 0.0
    next_push = 0.0
    next_ag = 0.0
    rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
    ag_status = (
        f"Antigravity {ag_interval:g} 秒"
        if (enable_antigravity and fetch_usage_text is not None)
        else "Antigravity 已關閉"
    )
    print(
        f"常駐模式啟動（Anthropic {fetch_interval:g} 秒、deskbar {push_interval:g} 秒、{ag_status}）"
    )
    while True:
        now = time.monotonic()

        if enable_antigravity and now >= next_ag:
            refresh_antigravity_async()
            next_ag = now + ag_interval

        now = time.monotonic()
        if cached is not None and now >= next_push:
            if enable_antigravity:
                cached.update(get_antigravity_fields())
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
                    url, token, enable_antigravity=enable_antigravity
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
    args = parser.parse_args()

    enable_ag = not args.no_antigravity

    if args.loop:
        run_loop(
            args.url,
            args.token,
            args.fetch_interval,
            args.push_interval,
            ag_interval=args.ag_interval,
            enable_antigravity=enable_ag,
        )
    else:
        one_cycle(args.url, args.token, enable_antigravity=enable_ag)


if __name__ == "__main__":
    main()

