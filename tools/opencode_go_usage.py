"""OpenCode Go 用量抓取工具。

OpenCode Go（opencode.ai/go 訂閱）是 API key 型 provider。
``GET https://opencode.ai/zen/go/v1/usage`` 帶 ``Authorization: Bearer <key>`` 回：

    {"usage": {"rolling": {"status": "ok", "percent": 0, "resetsAt": "…Z"},
               "weekly":  {...}, "monthly": {...}}}

rolling 實測是 5 小時視窗（resetsAt − now ≈ 5h）。唯讀端點，不花額度。
所有 I/O 失敗一律回 None，不讓推送 agent 掛掉。

key 取得順序（2026-09-23 起多把 key，每行一把，每把一張卡片）：
1. 環境變數 OPENCODE_GO_API_KEY（逗號或換行分隔多把）
2. 本機檔 ~/.deskbar-agent/opencode.key（純文字，一行一把）
3. ~/.local/share/opencode/auth.json 的 opencode-go.key（舊行為，單把）

帳號 id 用 key 的 sha256 前 12 碼（key 原文、前綴絕不進 payload／log）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import requests

OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
DEFAULT_KEY_PATH = Path.home() / ".deskbar-agent" / "opencode.key"
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
PROVIDER_KEY = "opencode-go"
ENV_VAR = "OPENCODE_GO_API_KEY"
# opencode.ai 前面的 Cloudflare 會擋沒有 User-Agent 的請求（CommandCode 同一問題，2026-09-23）
USER_AGENT = "deskbar-opencode/1.0"
WINDOWS = ("rolling", "weekly", "monthly")
_MAX_KEYS = 8


def _split_key_text(text: Any) -> list[str]:
    """把逗號／換行分隔的多把 key 拆開：去空行去重、保序、上限 _MAX_KEYS。"""
    if not isinstance(text, str):
        return []
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in text.replace(",", "\n").splitlines():
        key = chunk.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        parts.append(key)
        if len(parts) >= _MAX_KEYS:
            break
    return parts


def _load_auth_json_key(auth_path=None) -> str | None:
    """舊行為：讀 opencode auth.json 的 opencode-go.key；檔壞、缺欄位一律回 None。"""
    path = OPENCODE_AUTH_PATH if auth_path is None else Path(auth_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    entry = data.get(PROVIDER_KEY) if isinstance(data, dict) else None
    key = entry.get("key") if isinstance(entry, dict) else None
    return key if isinstance(key, str) and key else None


def load_api_keys(
    env: dict | None = None,
    key_path: Path | str | None = None,
    auth_path: Path | str | None = None,
) -> list[str]:
    """讀 OpenCode Go 的全部 API key，依序：環境變數 → 本機 key 檔 → auth.json。"""
    env_dict = os.environ if env is None else env
    raw = env_dict.get(ENV_VAR)
    keys = _split_key_text(raw) if isinstance(raw, str) else []
    if keys:
        return keys

    file_path = DEFAULT_KEY_PATH if key_path is None else Path(key_path).expanduser()
    try:
        if file_path.is_file():
            keys = _split_key_text(file_path.read_text(encoding="utf-8"))
            if keys:
                return keys
    except OSError:
        pass

    single = _load_auth_json_key(auth_path)
    return [single] if single else []


def load_api_key(
    env: dict | None = None,
    key_path: Path | str | None = None,
    auth_path: Path | str | None = None,
) -> str | None:
    """讀 OpenCode Go 的 API key（第一把，給舊呼叫者用）。"""
    keys = load_api_keys(env=env, key_path=key_path, auth_path=auth_path)
    return keys[0] if keys else None


def key_id(key: str) -> str:
    """key 的穩定 id：sha256 前 12 碼。key 原文、前綴絕不外流。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _to_pct(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    # 上游超額時可能 >100；壓回 0–100 照收（全專案規則，Pi 端也是這樣收）
    return max(0.0, min(100.0, pct))


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


def _get_client(http: Any):
    client = requests if http is None else http
    get = getattr(client, "get", None)
    if get is None:
        if not callable(client):
            return None
        get = client
    return get


def fetch_account(key: str, http: Any = None) -> dict | None:
    """抓單一把 key 的 OpenCode Go 用量。

    回 {"account_id"（sha12）, "name"（""）, rolling/weekly/monthly 各 pct/resets_at}；
    401/403 回 None（呼叫端略過這張卡片）；其他失敗也回 None。key 原文絕不印出。
    """
    if not isinstance(key, str) or not key.strip():
        return None
    key = key.strip()
    get = _get_client(http)
    if get is None:
        return None
    headers = {"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    try:
        response = get(USAGE_URL, headers=headers, timeout=20)
    except Exception as error:
        print(f"[OpenCode] 抓取失敗：{type(error).__name__}")
        return None
    status_code = getattr(response, "status_code", None)
    if status_code in (401, 403):
        print("[OpenCode] key 被拒")
        return None
    if status_code != 200:
        print(f"[OpenCode] 抓取失敗：HTTP {status_code}")
        return None
    try:
        data = response.json()
    except (ValueError, TypeError):
        print("[OpenCode] 抓取失敗：回應不是合法 JSON")
        return None
    result = parse_usage(data)
    result["account_id"] = key_id(key)
    result["name"] = ""
    return result


def fetch_accounts(
    keys: list[str] | None = None,
    http: Any = None,
    env: dict | None = None,
    key_path: Path | str | None = None,
    auth_path: Path | str | None = None,
) -> list[dict]:
    """逐把 key 呼叫 fetch_account，被拒／失敗的略過；回傳順序照 keys。無 key 回 []。"""
    if keys is None:
        keys = load_api_keys(env=env, key_path=key_path, auth_path=auth_path)
    accounts: list[dict] = []
    for key in keys or []:
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            account = fetch_account(key, http=http)
        except Exception as error:
            print(f"[OpenCode] 抓取失敗：{type(error).__name__}")
            account = None
        if account is not None:
            accounts.append(account)
    return accounts


def fetch_usage(
    http: Any = None,
    env: dict | None = None,
    key_path: Path | str | None = None,
    auth_path: Path | str | None = None,
) -> dict | None:
    """抓 OpenCode Go 用量（第一把 key；相容舊呼叫者）＝ fetch_account(第一把 key)。"""
    keys = load_api_keys(env=env, key_path=key_path, auth_path=auth_path)
    if not keys:
        print("[OpenCode] 抓取失敗：找不到 API key")
        return None
    try:
        return fetch_account(keys[0], http=http)
    except Exception as error:
        print(f"[OpenCode] 抓取失敗：{type(error).__name__}")
        return None
