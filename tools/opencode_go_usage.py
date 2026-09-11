"""OpenCode Go 用量抓取工具。

2026-09-11 實機驗證：OpenCode Go（opencode.ai/go 訂閱）是 API key 型 provider，
key 存在 ``~/.local/share/opencode/auth.json`` 的 ``opencode-go.key``。
``GET https://opencode.ai/zen/go/v1/usage`` 帶 ``Authorization: Bearer <key>`` 回：

    {"usage": {"rolling": {"status": "ok", "percent": 0, "resetsAt": "…Z"},
               "weekly":  {...}, "monthly": {...}}}

rolling 實測是 5 小時視窗（resetsAt − now ≈ 5h）。唯讀端點，不花額度。
所有 I/O 失敗一律回 None，不讓推送 agent 掛掉。
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
PROVIDER_KEY = "opencode-go"
WINDOWS = ("rolling", "weekly", "monthly")


def load_api_key(auth_path=None) -> str | None:
    """讀 opencode-go 的 API key；檔壞、缺欄位一律回 None。"""
    path = OPENCODE_AUTH_PATH if auth_path is None else Path(auth_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    entry = data.get(PROVIDER_KEY) if isinstance(data, dict) else None
    key = entry.get("key") if isinstance(entry, dict) else None
    return key if isinstance(key, str) and key else None


def _to_pct(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    return pct if 0 <= pct <= 100 else None


def parse_usage(data) -> dict:
    """純函數：三個視窗各回 ``<window>_pct`` / ``<window>_resets_at``；壞資料回 None。"""
    out = {}
    for window in WINDOWS:
        out[f"{window}_pct"] = None
        out[f"{window}_resets_at"] = None
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return out
    for window in WINDOWS:
        entry = usage.get(window)
        if not isinstance(entry, dict):
            continue
        out[f"{window}_pct"] = _to_pct(entry.get("percent"))
        resets_at = entry.get("resetsAt")
        out[f"{window}_resets_at"] = resets_at if isinstance(resets_at, str) and resets_at else None
    return out


def fetch_usage(auth_path=None, http=None) -> dict | None:
    """抓 OpenCode Go 用量；任何失敗回 None。"""
    try:
        key = load_api_key(auth_path)
        if key is None:
            print("[OpenCode Go] 抓取失敗：auth.json 沒有 opencode-go 的 key")
            return None
        client = requests if http is None else http
        get = getattr(client, "get", None)
        if get is None:
            if not callable(client):
                return None
            get = client
        response = get(USAGE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=20)
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            print(f"[OpenCode Go] 抓取失敗：HTTP {status_code}")
            return None
        try:
            data = response.json()
        except (ValueError, TypeError):
            print("[OpenCode Go] 抓取失敗：回應不是合法 JSON")
            return None
        return parse_usage(data)
    except Exception as error:
        print(f"[OpenCode Go] 抓取失敗：{type(error).__name__}")
        return None
