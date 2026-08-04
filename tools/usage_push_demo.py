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
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CACHE_PATH = Path.home() / ".deskbar-agent" / "usage_cache.json"
DEFAULT_FETCH_INTERVAL = 300.0
DEFAULT_PUSH_INTERVAL = 60.0
INITIAL_RATE_LIMIT_BACKOFF = 900.0
MAX_RATE_LIMIT_BACKOFF = 3600.0


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


def build_payload(usage: dict) -> dict:
    five_hour = usage.get("five_hour") or {}
    seven_day = usage.get("seven_day") or {}
    fable_pct, fable_resets_at = None, None
    for limit in usage.get("limits") or []:
        if limit.get("kind") == "weekly_scoped":
            fable_pct = limit.get("percent")
            fable_resets_at = limit.get("resets_at")
            break
    return {
        "session_pct": five_hour.get("utilization"),
        "session_resets_at": five_hour.get("resets_at"),
        "weekly_pct": seven_day.get("utilization"),
        "weekly_resets_at": seven_day.get("resets_at"),
        "fable_pct": fable_pct,
        "fable_resets_at": fable_resets_at,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


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
    return (
        f"5h {payload.get('session_pct')}%  週 {payload.get('weekly_pct')}%  "
        f"fable {payload.get('fable_pct')}%"
    )


def one_cycle(url: str, token: str | None) -> dict:
    payload = build_payload(fetch_usage(load_access_token()))
    save_cache(payload)
    push(payload, url, token)
    print(f"已抓取並推送：{_summary(payload)}")
    return payload


def run_loop(
    url: str,
    token: str | None,
    fetch_interval: float,
    push_interval: float,
) -> None:
    cached = load_cache()
    next_fetch = 0.0
    next_push = 0.0
    rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
    print(
        f"常駐模式啟動（Anthropic {fetch_interval:g} 秒、deskbar {push_interval:g} 秒）"
    )
    while True:
        now = time.monotonic()
        if cached is not None and now >= next_push:
            try:
                push(cached, url, token)
                print(f"已補送快取：{_summary(cached)}")
            except SystemExit as error:
                print(f"快取推送失敗：{error}")
            next_push = now + push_interval

        now = time.monotonic()
        if now >= next_fetch:
            try:
                cached = one_cycle(url, token)
                next_fetch = now + fetch_interval
                next_push = now + push_interval
                rate_limit_backoff = INITIAL_RATE_LIMIT_BACKOFF
            except RateLimitedError as error:
                wait = max(rate_limit_backoff, error.retry_after or 0.0)
                next_fetch = now + wait
                rate_limit_backoff = min(rate_limit_backoff * 2.0,
                                         MAX_RATE_LIMIT_BACKOFF)
                print(f"Anthropic 429，{round(wait)} 秒後再抓；期間補送本機快取")
            except SystemExit as error:
                next_fetch = now + fetch_interval
                print(f"抓取失敗：{error}；期間補送本機快取")

        next_event = min(next_fetch, next_push if cached is not None else next_fetch)
        time.sleep(max(1.0, min(5.0, next_event - time.monotonic())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="deskbar /api/usage 完整網址")
    parser.add_argument("--token", default=None, help="選填 X-Deskbar-Token")
    parser.add_argument("--loop", action="store_true", help="常駐可靠推送模式")
    parser.add_argument("--fetch-interval", type=float,
                        default=DEFAULT_FETCH_INTERVAL)
    parser.add_argument("--push-interval", type=float,
                        default=DEFAULT_PUSH_INTERVAL)
    args = parser.parse_args()

    if args.loop:
        run_loop(args.url, args.token, args.fetch_interval, args.push_interval)
    else:
        one_cycle(args.url, args.token)


if __name__ == "__main__":
    main()
