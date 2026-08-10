"""OpenAI (ChatGPT) 用量抓取工具。

2026-08-10 實機驗證：ChatGPT 用量只能從 Codex responses API 的回應 header 取得，
chatgpt.com/backend-api/* 的唯讀 GET 端點都會被 Cloudflare 擋成 403 HTML。
因此本模組保留純 header 解析函數，實際抓取則集中在可注入 HTTP client 的 I/O 函數。
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import requests

AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_BODY = {
    "model": "gpt-5.5",
    "instructions": "reply with just: ok",
    "input": [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hi"}],
        }
    ],
    "stream": True,
    "store": False,
}
USER_AGENT = "codex_cli_rs/0.51.0 (Mac OS 26.4; arm64) Apple_Terminal"


def _header_map(headers) -> dict[str, object]:
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(k).lower(): v for k, v in items}


def _to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_codex_headers(headers: dict) -> dict:
    """純函數：解析 Codex responses header，key 大小寫不敏感且任何壞值都回 None。"""
    h = _header_map(headers)
    return {
        "used_pct": _to_float(h.get("x-codex-primary-used-percent")),
        "resets_at_epoch": _to_int(h.get("x-codex-primary-reset-at")),
        "plan": h.get("x-codex-plan-type"),
    }


def _load_auth(auth_path) -> tuple[str, str] | None:
    path = Path(auth_path).expanduser() if auth_path is not None else AUTH_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    openai = data.get("openai") if isinstance(data, dict) else None
    if not isinstance(openai, dict):
        return None
    access = openai.get("access")
    account_id = openai.get("accountId")
    if not isinstance(access, str) or not access:
        return None
    if not isinstance(account_id, str) or not account_id:
        return None
    return access, account_id


def _drain_response(response) -> None:
    try:
        if hasattr(response, "iter_content"):
            for _ in response.iter_content(chunk_size=8192):
                pass
        elif hasattr(response, "read"):
            response.read()
        elif hasattr(response, "content"):
            _ = response.content
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()


def fetch_usage(auth_path=None, http=None) -> dict | None:
    """抓取 OpenAI primary 週用量。

    這會消耗一點點額度：2026-08-10 實機驗證，Cloudflare 擋掉所有唯讀端點，
    只能靠帶 `originator: codex_cli_rs` 的真實 Codex responses 請求從回應 header 取得
    ChatGPT 額度。因此呼叫端必須低頻排程，只在剛使用 opencode 後或長間隔兜底刷新。
    任何檔案、JSON、網路、HTTP 狀態或 header 解析例外都回 None，不讓推送 agent 掛掉。
    """
    try:
        auth = _load_auth(auth_path)
        if auth is None:
            return None
        access, account_id = auth
        headers = {
            "Authorization": f"Bearer {access}",
            "chatgpt-account-id": account_id,
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "session_id": str(uuid4()),
            "User-Agent": USER_AGENT,
            "Accept": "text/event-stream",
        }

        client = requests if http is None else http
        post = getattr(client, "post", None)
        if post is None:
            if not callable(client):
                return None
            post = client
        response = post(
            CODEX_RESPONSES_URL,
            headers=headers,
            json=CODEX_BODY,
            stream=True,
            timeout=30,
        )
        _drain_response(response)
        if getattr(response, "status_code", None) != 200:
            return None
        return parse_codex_headers(getattr(response, "headers", {}))
    except Exception:
        return None
