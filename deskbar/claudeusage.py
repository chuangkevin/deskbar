"""Claude Code usage（用量）唯讀資料層：OAuth token 存取/刷新＋usage API 解析。

權限最小化鐵則：本模組（與 tools/claude_login.py 的登入流程）只跟 Claude 要
usage 唯讀所需的 SCOPE="user:profile"——不得加 org:create_api_key，也不得加任何
inference/write 用途的 scope。deskbar 只是把「這個月用了多少」畫出來，沒有理由
拿到能建 API key 或呼叫模型的權限；萬一這份長期存在 Pi 上、600 權限的 token 檔
外洩，範圍也僅止於讀個人 usage，不是一張萬用鑰匙。

OAUTH_JSON（config_dir()/"claude_oauth.json"，600）欄位：
    {access_token, refresh_token, expires_at, scope}
expires_at 一律存 epoch 秒（float，time.time() 基準）——不用 ISO 字串，跟
refresh_if_needed() 的到期比較直接用同一個時間基準，不必來回轉換時區。

刻意不把 OAUTH_JSON 做成「模組載入當下就算好的常數」：這支所有函式都呼叫
oauth_path()（呼叫當下才讀 config.config_dir()），理由跟 deskbar.config._path()
一樣——測試普遍用 monkeypatch.setenv("DESKBAR_CONFIG_DIR", tmp_path) 換路徑，
如果 OAUTH_JSON 是 import 當下就算好的模組常量，這招就會失效。
"""
from __future__ import annotations

import json
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from deskbar import config

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
SCOPE = "user:profile"          # 唯讀權限最小化：不得含 create_api_key／inference/write

OAUTH_FILE_NAME = "claude_oauth.json"
REFRESH_MARGIN_S = 300           # expires_at - now < 300 秒就先換新，避免 usage 請求途中過期
TZ = ZoneInfo("Asia/Taipei")


def oauth_path() -> Path:
    """OAUTH_JSON 的實際路徑；每次呼叫當下才解析 config_dir()（見檔頭說明）。"""
    return config.config_dir() / OAUTH_FILE_NAME


@dataclass(frozen=True)
class UsageInfo:
    session_pct: float | None
    session_resets_at: datetime | None
    weekly_pct: float | None
    weekly_resets_at: datetime | None
    fable_pct: float | None
    fable_resets_at: datetime | None
    fetched_at: datetime
    needs_login: bool = False


def _empty_usage(fetched_at: datetime, needs_login: bool) -> UsageInfo:
    return UsageInfo(None, None, None, None, None, None, fetched_at, needs_login)


def load_token() -> dict | None:
    """讀 OAUTH_JSON；檔案不存在或格式壞掉一律回 None，不拋例外。"""
    try:
        return json.loads(oauth_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_token(tok: dict) -> None:
    """寫入 OAUTH_JSON 並收緊權限成 600——這份檔案能讀到使用者的 Claude 帳號用量，
    雖然 scope 已經最小化到唯讀，仍比照一般憑證檔處理。"""
    p = oauth_path()
    p.write_text(json.dumps(tok, ensure_ascii=False), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass    # 非 POSIX 檔案系統（理論上用不到，防禦性略過）


def refresh_if_needed(http_post=requests.post, now_fn=_time.time) -> dict | None:
    """回傳目前可用的 token dict（沿用或剛換新的）；回 None＝需要重新登入
    （tools/claude_login.py）。

    - 沒有 token 檔：回 None。
    - expires_at 距現在 >= REFRESH_MARGIN_S：直接沿用現有 token，不打網路。
    - 否則用 refresh_token 換新：成功就持久化輪替後的 token 並回傳；
      伺服器回 4xx（refresh_token 本身失效）→ 回 None（需要重新登入）；
      網路暫時失敗（連不上/逾時）不代表帳號真的失效，手上的舊 token 先將就用
      （usage API 若真的過期會回 401，由 fetch_usage 那層轉成 needs_login）。
    """
    tok = load_token()
    if tok is None:
        return None
    expires_at = tok.get("expires_at")
    has_expiry = isinstance(expires_at, (int, float))
    if has_expiry and expires_at - now_fn() >= REFRESH_MARGIN_S:
        return tok

    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        return tok if has_expiry else None

    try:
        resp = http_post(TOKEN_URL, json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        }, timeout=15)
    except requests.RequestException:
        return tok if has_expiry else None

    if resp.status_code >= 400:
        return None    # refresh_token 失效／被撤銷：需要重新登入

    try:
        body = resp.json()
    except ValueError:
        return tok if has_expiry else None

    new_tok = {
        "access_token": body.get("access_token", tok.get("access_token")),
        "refresh_token": body.get("refresh_token", refresh_token),
        "expires_at": now_fn() + float(body.get("expires_in", 3600)),
        "scope": body.get("scope", tok.get("scope", SCOPE)),
    }
    save_token(new_tok)
    return new_tok


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _parse_dt(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_fable_limit(limits) -> tuple[float | None, datetime | None]:
    if not isinstance(limits, list):
        return None, None
    for item in limits:
        if not isinstance(item, dict):
            continue
        try:
            name = item.get("scope", {}).get("model", {}).get("display_name", "")
        except AttributeError:
            name = ""
        if isinstance(name, str) and "Fable" in name:
            return _num(item.get("utilization")), _parse_dt(item.get("resets_at"))
    return None, None


def fetch_usage(http_get=requests.get, now_fn=lambda: datetime.now(TZ)) -> UsageInfo:
    """唯讀抓一次 usage；任何失敗都回傳 UsageInfo（needs_login 區分「要重新登入」
    跟「暫時抓不到、保留舊值就好」），不對呼叫端拋例外——呼叫端（start_usage_thread）
    才不必再包一層 try/except 才能安全跑常駐迴圈。"""
    now = now_fn()
    tok = refresh_if_needed()
    if tok is None:
        return _empty_usage(now, needs_login=True)

    headers = {
        "Authorization": f"Bearer {tok.get('access_token', '')}",
        "anthropic-beta": USAGE_BETA_HEADER,
    }
    try:
        resp = http_get(USAGE_URL, headers=headers, timeout=15)
    except requests.RequestException:
        return _empty_usage(now, needs_login=False)

    if resp.status_code in (401, 403):
        return _empty_usage(now, needs_login=True)
    if resp.status_code >= 400:
        return _empty_usage(now, needs_login=False)

    try:
        body = resp.json()
    except ValueError:
        return _empty_usage(now, needs_login=False)
    if not isinstance(body, dict):
        return _empty_usage(now, needs_login=False)

    five_hour = body.get("five_hour") or {}
    seven_day = body.get("seven_day") or {}
    fable_pct, fable_resets_at = _find_fable_limit(body.get("limits"))

    return UsageInfo(
        session_pct=_num(five_hour.get("utilization")),
        session_resets_at=_parse_dt(five_hour.get("resets_at")),
        weekly_pct=_num(seven_day.get("utilization")),
        weekly_resets_at=_parse_dt(seven_day.get("resets_at")),
        fable_pct=fable_pct,
        fable_resets_at=fable_resets_at,
        fetched_at=now,
        needs_login=False,
    )


def fmt_countdown(dt: datetime | None, now: datetime) -> str:
    """純函數：把「距 dt 還有多久」格式成人看得懂的倒數字串。
    >=1 天→「1d 4h」；<1 天→「2h 03m」；<1 分鐘（含已過期）→「即將重置」；
    dt 為 None（沒有這筆資料）→「—」。"""
    if dt is None:
        return "—"
    total_minutes = int((dt - now).total_seconds() // 60)
    if total_minutes < 1:
        return "即將重置"
    days, rem_after_days = divmod(total_minutes, 60 * 24)
    if days >= 1:
        hours = rem_after_days // 60
        return f"{days}d {hours}h"
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


_fetch_usage = fetch_usage    # 測試注入點（比照 sync.py 的 _get_token/_fetch_range）


def start_usage_thread(state, interval: int = 60) -> bool:
    """背景 daemon thread：每 interval 秒 fetch_usage() 一次並 state.set_usage(info)。
    沒有登入過（OAUTH_JSON 不存在）就不啟動——回 False，呼叫端（__main__.py）不需要
    另外判斷，直接呼叫即可，不影響沒設定這個功能的機器。例外一律吞掉保留舊值，
    常駐迴圈不該因為一次網路失敗就死掉（比照 sync.py 的 weather_sync_once）。"""
    if not oauth_path().exists():
        return False

    def loop():
        while True:
            try:
                info = _fetch_usage()
                state.set_usage(info)
            except Exception:
                pass    # 保留舊值；下一輪再試
            _time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    return True
