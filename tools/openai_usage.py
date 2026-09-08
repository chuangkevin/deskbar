"""OpenAI (ChatGPT) 用量抓取工具。

2026-08-10 實機驗證：ChatGPT 用量只能從 Codex responses API 的回應 header 取得，
chatgpt.com/backend-api/* 的唯讀 GET 端點都會被 Cloudflare 擋成 403 HTML。
因此本模組保留純 header 解析函數，實際抓取則集中在可注入 HTTP client 的 I/O 函數。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

import requests

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
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


def _account_id_from_jwt(access_token: str) -> str | None:
    """從 JWT payload 取帳號；憑證格式不完整時仍不可讓抓取程序中斷。"""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        auth_claim = claims.get("https://api.openai.com/auth")
        account_id = auth_claim.get("chatgpt_account_id") if isinstance(auth_claim, dict) else None
        return account_id if isinstance(account_id, str) and account_id else None
    except (AttributeError, IndexError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _valid_account_id(value) -> str | None:
    if not isinstance(value, str):
        return None
    account_id = value.strip()
    return account_id or None


def _valid_usage_pct(value) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return False
    return 0 <= pct <= 100


def _read_credentials(path, token_key: str, account_key: str, section: str) -> tuple[str, str] | None:
    """讀取單一憑證格式；壞檔或不完整資料一律交由下一個來源接手。"""
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        values = data.get(section) if isinstance(data, dict) else None
        access = values.get(token_key) if isinstance(values, dict) else None
        account_id = values.get(account_key) if isinstance(values, dict) else None
        if not isinstance(access, str) or not access:
            return None
        if not isinstance(account_id, str) or not account_id:
            account_id = _account_id_from_jwt(access) or ""
        return access, account_id
    except (OSError, TypeError, ValueError):
        return None


def load_credentials(codex_path=None, opencode_path=None) -> tuple:
    """回 (access_token, account_id)；都拿不到回 (None, None)。不拋例外。"""
    # 2026-08-10 實測 OpenCode token 雖標示有效仍回 HTTP 401 token_expired；
    # 委派改用 Codex CLI 後，必須優先讀會被 CLI 持續換發的憑證。
    codex = _read_credentials(
        CODEX_AUTH_PATH if codex_path is None else codex_path,
        "access_token",
        "account_id",
        "tokens",
    )
    if codex is not None:
        return codex
    opencode = _read_credentials(
        OPENCODE_AUTH_PATH if opencode_path is None else opencode_path,
        "access",
        "accountId",
        "openai",
    )
    return opencode if opencode is not None else (None, None)


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
    ChatGPT 額度。因此呼叫端必須低頻排程，只在剛使用 Codex CLI 後或長間隔兜底刷新。
    任何檔案、JSON、網路、HTTP 狀態或 header 解析例外都回 None，不讓推送 agent 掛掉。
    """
    try:
        # auth_path 保留給舊呼叫端與測試，代表指定 OpenCode 格式路徑。
        access, account_id = load_credentials(opencode_path=auth_path)
        if access is None:
            print("[OpenAI] 抓取失敗：找不到可用憑證")
            return None
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
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            print(f"[OpenAI] 抓取失敗：HTTP {status_code}")
            return None
        parsed = parse_codex_headers(getattr(response, "headers", {}))
        if _valid_usage_pct(parsed.get("used_pct")):
            credential_account_id = _valid_account_id(account_id)
            if credential_account_id is not None:
                parsed["account_id"] = credential_account_id
        return parsed
    except Exception as error:
        print(f"[OpenAI] 抓取失敗：{type(error).__name__}")
        return None
