"""OpenAI (ChatGPT) 用量抓取工具。

2026-08-10 實機驗證：ChatGPT 用量只能從 Codex responses API 的回應 header 取得，
chatgpt.com/backend-api/* 的唯讀 GET 端點都會被 Cloudflare 擋成 403 HTML。
因此本模組保留純 header 解析函數，實際抓取則集中在可注入 HTTP client 的 I/O 函數。
"""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from uuid import uuid4

import requests

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
OPENCODE_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
OPENAI_ACCOUNTS_CONFIG_PATH = Path.home() / ".deskbar-agent" / "openai_accounts.json"
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

_CREDENTIAL_FORMATS = {
    "codex": ("access_token", "account_id", "tokens"),
    "opencode": ("access", "accountId", "openai"),
}


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


def _valid_usage_pct(value) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return False
    return 0 <= pct <= 100


def _jwt_payload(access_token: str) -> dict | None:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return claims if isinstance(claims, dict) else None
    except (
        AttributeError,
        IndexError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
    ):
        return None


def _account_id_from_jwt(access_token: str) -> str | None:
    """從 JWT payload 取帳號；憑證格式不完整時仍不可讓抓取程序中斷。"""
    claims = _jwt_payload(access_token)
    if claims is None:
        return None
    try:
        auth_claim = claims.get("https://api.openai.com/auth")
        account_id = auth_claim.get("chatgpt_account_id") if isinstance(auth_claim, dict) else None
        return account_id if isinstance(account_id, str) and account_id else None
    except (AttributeError, TypeError):
        return None


def _name_from_jwt_claims(claims: dict, account_id: str) -> str:
    profile = claims.get("https://api.openai.com/profile")
    email = profile.get("email") if isinstance(profile, dict) else None
    if not isinstance(email, str) or not email:
        email = claims.get("email")
    if isinstance(email, str) and email:
        return email.split("@", 1)[0]
    return account_id[:8]


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


def _guess_auth_format(path) -> str:
    return "opencode" if "opencode" in str(path).lower() else "codex"


def _read_credential(path, auth_format: str) -> dict | None:
    keys = _CREDENTIAL_FORMATS.get(auth_format)
    if keys is None:
        return None
    token_key, account_key, section = keys
    expanded = Path(path).expanduser()
    pair = _read_credentials(expanded, token_key, account_key, section)
    if pair is None:
        return None
    access, account_id = pair
    if not account_id:
        return None
    claims = _jwt_payload(access)
    if claims is None:
        return None
    return {
        "access": access,
        "account_id": account_id,
        "name": _name_from_jwt_claims(claims, account_id),
        "source": str(expanded),
    }


def _configured_auth_sources(config_path) -> list[tuple[Path, str]] | None:
    path = OPENAI_ACCOUNTS_CONFIG_PATH if config_path is None else Path(config_path).expanduser()
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(entries, list):
        return None

    sources = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        auth_path = entry.get("auth")
        if not isinstance(auth_path, str) or not auth_path:
            continue
        auth_format = entry.get("format")
        if not isinstance(auth_format, str) or not auth_format:
            auth_format = _guess_auth_format(auth_path)
        sources.append((Path(auth_path).expanduser(), auth_format))
    return sources


def list_credentials(config_path=None) -> list[dict]:
    """列出所有可用 OpenAI credentials；壞來源只跳過，不中斷整體流程。"""
    sources = _configured_auth_sources(config_path)
    if sources is None:
        sources = [
            (CODEX_AUTH_PATH, "codex"),
            (OPENCODE_AUTH_PATH, "opencode"),
        ]

    credentials = []
    seen_account_ids = set()
    for path, auth_format in sources:
        credential = _read_credential(path, auth_format)
        if credential is None:
            continue
        account_id = credential["account_id"]
        if account_id in seen_account_ids:
            continue
        seen_account_ids.add(account_id)
        credentials.append(credential)
    return credentials


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


def _fetch_usage_headers(access: str, account_id: str, http=None) -> dict | None:
    try:
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
        parsed = parse_codex_headers(getattr(response, "headers", {}))
        has_valid_usage = _valid_usage_pct(parsed.get("used_pct"))
        if status_code != 200:
            if not has_valid_usage:
                print(f"[OpenAI] 抓取失敗：HTTP {status_code}")
                return None
            print(f"[OpenAI] HTTP {status_code}，改用回應 header 的用量")
        return parsed
    except Exception as error:
        print(f"[OpenAI] 抓取失敗：{type(error).__name__}")
        return None


def fetch_usage(auth_path=None, http=None) -> dict | None:
    """抓取 OpenAI primary 週用量。

    這會消耗一點點額度：2026-08-10 實機驗證，Cloudflare 擋掉所有唯讀端點，
    只能靠帶 `originator: codex_cli_rs` 的真實 Codex responses 請求從回應 header 取得
    ChatGPT 額度。因此呼叫端必須低頻排程，只在剛使用 Codex CLI 後或長間隔兜底刷新。
    任何檔案、JSON、網路、HTTP 狀態或 header 解析例外都回 None，不讓推送 agent 掛掉。
    """
    # auth_path 保留給舊呼叫端與測試，代表指定 OpenCode 格式路徑。
    access, account_id = load_credentials(opencode_path=auth_path)
    if access is None:
        print("[OpenAI] 抓取失敗：找不到可用憑證")
        return None
    return _fetch_usage_headers(access, account_id, http=http)


def fetch_usage_for(credential: dict, http=None) -> dict | None:
    access = credential.get("access") if isinstance(credential, dict) else None
    account_id = credential.get("account_id") if isinstance(credential, dict) else None
    if not isinstance(access, str) or not access or not isinstance(account_id, str):
        return None
    parsed = _fetch_usage_headers(access, account_id, http=http)
    if parsed is None:
        return None
    parsed = dict(parsed)
    parsed["account_id"] = account_id
    name = credential.get("name") if isinstance(credential.get("name"), str) else None
    parsed["name"] = name or account_id[:8]
    return parsed


def fetch_all_usage(config_path=None, http=None) -> list[dict]:
    results = []
    for credential in list_credentials(config_path=config_path):
        parsed = fetch_usage_for(credential, http=http)
        if parsed is not None:
            results.append(parsed)
    return results
