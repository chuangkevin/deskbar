"""獨立小工具：讀本機 macOS Keychain 的 Claude Code 憑證、打官方 usage API，
POST 到 deskbar 的 /api/usage。不想改既有 agent（例如
claude-usage-cube/agent/cube_agent.py）、或單純想單獨驗證推送路徑通不通時，
跑這支就好。

用法：
    .venv/bin/python tools/usage_push_demo.py --url http://deskbar.local:8080/api/usage
    .venv/bin/python tools/usage_push_demo.py --url http://deskbar.local:8080/api/usage \\
        --token <跟 Pi 上 DESKBAR_PUSH_TOKEN 一樣的字串>
    .venv/bin/python tools/usage_push_demo.py --url ... --loop     # 常駐，每 60 秒一輪

前置：這台 Mac 要登入過 Claude Code——Keychain 服務名稱「Claude Code-credentials」
底下要有憑證，跟 claude-usage-cube/agent/cube_agent.py 讀的是同一份。

跟 tools/usage_push_snippet.py 的差異：這支自己完整處理「讀憑證→打 API→推送」
一條龍，獨立執行不需要嵌進任何既有腳本；usage_push_snippet.py 只有最後一步
（推送），給已經有自己 usage 抓取邏輯的人直接複製函數用。

失敗一律用 SystemExit 帶清楚訊息中止（單次模式）或印出來跳過本輪
（--loop 模式），不吞成無聲的空白畫面。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time

import requests

KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
# 官方 usage API 對沒有瀏覽器 UA 的請求較容易觸發風控，比照 cube_agent.py 帶一個
# 常見瀏覽器 UA 字串。
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def load_access_token() -> str:
    """讀 macOS Keychain 的 Claude Code 憑證。讀不到／過期都直接報錯中止——這支
    是單次診斷/示範工具，不像常駐 agent 那樣該悄悄跳過。"""
    r = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise SystemExit(
            f"讀不到 Keychain 項目「{KEYCHAIN_SERVICE}」——這台 Mac 登入過 Claude Code 嗎？\n"
            f"stderr: {r.stderr.strip()}")
    try:
        oauth = json.loads(r.stdout.strip()).get("claudeAiOauth", {})
    except json.JSONDecodeError as e:
        raise SystemExit(f"Keychain 內容不是預期的 JSON：{e}")
    token = oauth.get("accessToken")
    if not token:
        raise SystemExit("Keychain 資料裡沒有 accessToken 欄位")
    expires_at = oauth.get("expiresAt", 0)
    if expires_at and expires_at / 1000 < time.time():
        raise SystemExit("token 已過期——開一下 Claude Code 讓它自動續期後再重跑")
    return token


def fetch_usage(token: str) -> dict:
    try:
        resp = requests.get(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": USAGE_BETA_HEADER,
            "User-Agent": UA,
        }, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SystemExit(f"打 usage API 失敗：{e}")
    try:
        return resp.json()
    except ValueError as e:
        raise SystemExit(f"usage API 回應不是合法 JSON：{e}")


def build_payload(usage: dict) -> dict:
    """把官方 usage API 回應轉成 deskbar POST /api/usage 要的形狀。fable 資料藏在
    limits 裡 kind=="weekly_scoped" 的項目（跟 claude-usage-cube/agent/cube_agent.py
    的解析邏輯一致）。"""
    five_hour = usage.get("five_hour") or {}
    seven_day = usage.get("seven_day") or {}
    fable_pct, fable_resets_at = None, None
    for lim in usage.get("limits") or []:
        if lim.get("kind") == "weekly_scoped":
            fable_pct = lim.get("percent")
            fable_resets_at = lim.get("resets_at")
            break
    return {
        "session_pct": five_hour.get("utilization"),
        "session_resets_at": five_hour.get("resets_at"),
        "weekly_pct": seven_day.get("utilization"),
        "weekly_resets_at": seven_day.get("resets_at"),
        "fable_pct": fable_pct,
        "fable_resets_at": fable_resets_at,
    }


def push(payload: dict, url: str, token: str | None) -> None:
    headers = {"X-Deskbar-Token": token} if token else {}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
    except requests.RequestException as e:
        raise SystemExit(f"推送到 deskbar 失敗：{e}")
    if resp.status_code != 204:
        raise SystemExit(f"deskbar 回應非預期：HTTP {resp.status_code} {resp.text[:200]}")


def one_cycle(url: str, token: str | None) -> None:
    payload = build_payload(fetch_usage(load_access_token()))
    push(payload, url, token)
    print(f"已推送：5h {payload['session_pct']}%  週 {payload['weekly_pct']}%  "
         f"fable {payload['fable_pct']}%")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="deskbar 的 /api/usage 完整網址")
    ap.add_argument("--token", default=None,
                    help="對應 Pi 上 DESKBAR_PUSH_TOKEN 環境變數（若有設定）")
    ap.add_argument("--loop", action="store_true", help="常駐模式，每 60 秒推一次")
    args = ap.parse_args()

    if not args.loop:
        one_cycle(args.url, args.token)
        return

    print("常駐模式啟動（每 60 秒一輪，Ctrl+C 結束）")
    while True:
        try:
            one_cycle(args.url, args.token)
        except SystemExit as e:
            print(f"跳過本輪：{e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
