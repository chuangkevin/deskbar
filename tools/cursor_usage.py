"""Cursor 用量抓取工具。

2026-09-10 實機驗證：Cursor 個人方案的用量只能從 dashboard 的
``GET https://cursor.com/api/usage-summary`` 取得，且必須帶 Origin/Referer
（缺了會被擋成 403 ``Invalid origin for state-changing request``）。
session token 在 macOS Keychain 的 ``cursor-access-token`` / ``cursor-user``，
由 Cursor 自己維護續期——本模組只讀不換，避免踢掉 CLI 的登入。

所有 I/O 失敗一律回 None，不讓推送 agent 掛掉。
"""
from __future__ import annotations

import base64
import binascii
import json
import subprocess
from urllib.parse import quote

import requests

USAGE_SUMMARY_URL = "https://cursor.com/api/usage-summary"
KEYCHAIN_SERVICE = "cursor-access-token"
KEYCHAIN_ACCOUNT = "cursor-user"
USER_AGENT = "Mozilla/5.0"


def load_token(runner=None) -> str | None:
    """從 Keychain 讀 Cursor session token；讀不到一律回 None。"""
    run = subprocess.run if runner is None else runner
    try:
        result = run(
            ["security", "find-generic-password", "-w",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    token = (getattr(result, "stdout", "") or "").strip()
    return token or None


def account_sub(token) -> str | None:
    """解 JWT payload 取 ``sub``；壞資料回 None。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (AttributeError, IndexError, TypeError, ValueError,
            UnicodeDecodeError, binascii.Error):
        return None
    if not isinstance(claims, dict):
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) and sub else None


def _to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_usage_summary(data) -> dict:
    """純函數：把 usage-summary 回應換算成 ``used_pct`` / ``resets_at`` / ``plan``。

    任何缺欄位、型別錯、百分比超出 0~100 都回 None，不拋例外。
    """
    empty = {"used_pct": None, "resets_at": None, "plan": None}
    if not isinstance(data, dict):
        return empty

    individual = data.get("individualUsage")
    plan_usage = individual.get("plan") if isinstance(individual, dict) else None
    used_pct = _to_float(plan_usage.get("totalPercentUsed")) if isinstance(plan_usage, dict) else None
    if used_pct is not None and not 0 <= used_pct <= 100:
        used_pct = None

    resets_at = data.get("billingCycleEnd")
    if not isinstance(resets_at, str) or not resets_at:
        resets_at = None

    plan = data.get("membershipType")
    if not isinstance(plan, str) or not plan:
        plan = None

    return {"used_pct": used_pct, "resets_at": resets_at, "plan": plan}


def fetch_usage(http=None, runner=None) -> dict | None:
    """抓 Cursor 個人方案用量；任何失敗回 None。"""
    try:
        token = load_token(runner=runner)
        if token is None:
            print("[Cursor] 抓取失敗：Keychain 沒有可用 token")
            return None
        sub = account_sub(token)
        if sub is None:
            print("[Cursor] 抓取失敗：token 解不出帳號")
            return None

        client = requests if http is None else http
        get = getattr(client, "get", None)
        if get is None:
            if not callable(client):
                return None
            get = client
        response = get(
            USAGE_SUMMARY_URL,
            headers={
                "Cookie": f"WorkosCursorSessionToken={quote(sub)}%3A%3A{token}",
                "Origin": "https://cursor.com",
                "Referer": "https://cursor.com/dashboard",
                "User-Agent": USER_AGENT,
            },
            timeout=20,
        )
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            print(f"[Cursor] 抓取失敗：HTTP {status_code}")
            return None
        try:
            data = response.json()
        except (ValueError, TypeError):
            print("[Cursor] 抓取失敗：回應不是合法 JSON")
            return None
        return parse_usage_summary(data)
    except Exception as error:
        print(f"[Cursor] 抓取失敗：{type(error).__name__}")
        return None
