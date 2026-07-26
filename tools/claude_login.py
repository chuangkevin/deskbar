"""Pi 端：讓使用者自己登入 Claude 帳號，取得 usage 唯讀 token 存進 Pi 本機。

刻意設計成「使用者親自在 Pi 上互動執行」，不是 AI 代跑的腳本：
1. 印出完整授權網址——使用者可以用手機/任何一台有瀏覽器的裝置打開它，
   deskbar 本身不需要瀏覽器（Pi Zero 2W 也裝不動）。
2. 登入完成後 Anthropic 的頁面會顯示一段授權碼，使用者把畫面上那一整串
   （可能是 "code#state" 或單純 "code"）貼回這支程式的終端機。
3. 程式拿授權碼跟 TOKEN_URL 換 access_token/refresh_token，寫進
   ~/.config/deskbar/claude_oauth.json（600），並立刻 fetch_usage() 一次印出
   三個百分比讓使用者當場確認有連上。

標準 OAuth2 PKCE(S256)，權限最小化：SCOPE 只要 usage 唯讀所需的 "user:profile"
（沿用 deskbar.claudeusage.SCOPE，不在這裡重複定義一份、也不額外加 scope）。

用法（在 Pi 上，repo 根目錄）：
    .venv/bin/python tools/claude_login.py
或透過 Mac 端：make claude-login（SSH 進 Pi 跑這支，見 Makefile）。
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import sys
import time
from urllib.parse import urlencode

import requests

from deskbar.claudeusage import (
    CLIENT_ID,
    SCOPE,
    TOKEN_URL,
    fetch_usage,
    oauth_path,
    save_token,
)

AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_pkce() -> tuple[str, str]:
    """回傳 (verifier, challenge)。verifier 43 字元（32 bytes base64url），
    challenge = base64url(sha256(verifier))，皆符合 RFC 7636 S256。"""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(challenge: str, state: str) -> str:
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def parse_pasted_code(raw: str) -> tuple[str, str]:
    """使用者貼回的授權碼支援 "code#state" 或單純 "code" 兩種格式，自動切開。
    沒有 "#state" 的話回傳的 state 是空字串，呼叫端應該退回用自己產生的 state。"""
    raw = raw.strip()
    code, sep, state = raw.partition("#")
    return code, state


def exchange_code(code: str, state: str, verifier: str,
                  http_post=requests.post) -> dict:
    resp = http_post(TOKEN_URL, json={
        "grant_type": "authorization_code",
        "code": code,
        "state": state,
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }, timeout=15)
    if resp.status_code != 200:
        raise SystemExit(f"換 token 失敗（HTTP {resp.status_code}）：{resp.text[:300]}")
    body = resp.json()
    if "access_token" not in body or "refresh_token" not in body:
        raise SystemExit(f"換 token 回應缺欄位：{body}")
    return {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + float(body.get("expires_in", 3600)),
        "scope": body.get("scope", SCOPE),
    }


def main() -> None:
    verifier, challenge = _make_pkce()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(challenge, state)

    print("請在任一裝置的瀏覽器打開下面這個網址登入 Claude 帳號：\n")
    print(url)
    print("\n登入後把畫面上顯示的授權碼整串貼回這裡（可能是 code#state 或單純 code）：")
    raw = sys.stdin.readline()
    if not raw.strip():
        raise SystemExit("沒有讀到輸入，中止。")
    code, pasted_state = parse_pasted_code(raw)
    if not code:
        raise SystemExit("看起來不是有效的授權碼，中止。")
    final_state = pasted_state or state

    tok = exchange_code(code, final_state, verifier)
    save_token(tok)
    print(f"\n已寫入 {oauth_path()}（600）")

    info = fetch_usage()
    if info.needs_login:
        print("警告：token 剛換好卻立刻回報需要重新登入，請確認網路/帳號狀態後重跑。")
    else:
        def _pct(v):
            return "—" if v is None else f"{round(v)}%"
        print("驗證用量讀取成功：")
        print(f"  5H SESSION：{_pct(info.session_pct)}")
        print(f"  本週：{_pct(info.weekly_pct)}")
        if info.fable_pct is not None:
            print(f"  FABLE：{_pct(info.fable_pct)}")

    print("\n重啟服務：sudo systemctl restart deskbar")


if __name__ == "__main__":
    main()
