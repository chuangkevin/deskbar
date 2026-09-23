"""CommandCode 用量抓取工具。

用量 API 端點：
    GET https://api.commandcode.ai/alpha/billing/credits
    Authorization: Bearer <API key>
    Accept: application/json

回傳 JSON 結構範例：
    {
      "credits": {"monthlyCredits": 45.07, "purchasedCredits": 0, "freeCredits": 0},
      "windowLimits": {
        "limited": true,
        "fiveHour": {"used": 0.5715, "cap": 14, "exceeded": false, "resetAt": 1790057273729},
        "weekly":   {"used": 24.922, "cap": 35, "exceeded": false, "resetAt": 1790357709248}
      }
    }

欄位說明：
- 百分比 = used / cap * 100（cap 為 0 或缺欄位時該視窗為 None）
- resetAt 為 epoch 毫秒，轉為 timezone-aware UTC datetime；exceeded 為 true 時仍照 used / cap 計算（可能 > 100）
- windowLimits.limited 為 false 或整段缺時各視窗為 None
- monthlyCredits 供記錄，不繪製於 deskbar 油表
- 401 / 403 回 None 並印 [CommandCode] API key 被拒；其他非 200 回 None
- 唯讀端點，不花額度

API key 取得順序：
1. 環境變數 COMMANDCODE_API_KEY
2. 本機檔 ~/.deskbar-agent/commandcode.key（純文字一行）
3. 透過 ssh 從 New API sqlite 唯讀取出：
   ssh -o BatchMode=yes -o ConnectTimeout=8 rpi-minicpm-jump python3 -
   SQL: select id, name, key from channels where base_url like '%commandcode%' and status = 1 limit 1
   成功後寫入快取 ~/.deskbar-agent/newapi_commandcode_key.json（0600）；ssh 失敗時讀快取
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import requests

NEWAPI_SSH_HOST = "rpi-minicpm-jump"
NEWAPI_DB_PATH = "/opt/newapi/data/one-api.db"
DEFAULT_KEY_PATH = Path.home() / ".deskbar-agent" / "commandcode.key"
DEFAULT_CACHE_PATH = Path.home() / ".deskbar-agent" / "newapi_commandcode_key.json"
USAGE_URL = "https://api.commandcode.ai/alpha/billing/credits"
SUBSCRIPTIONS_URL = "https://api.commandcode.ai/alpha/billing/subscriptions"
WHOAMI_URL = "https://api.commandcode.ai/alpha/whoami"
# CommandCode 前面的 Cloudflare 會擋沒有 User-Agent 的請求（403 error 1010，2026-09-23 實測）
USER_AGENT = "deskbar-commandcode/1.0"
_MAX_KEYS = 8


def _newapi_remote_script(db_path: str) -> str:
    """遠端唯讀腳本：從 New API sqlite 取出 CommandCode channel 的 key（純讀取，絕不 UPDATE）。"""
    return f"""
import json
import sqlite3

key = None
try:
    conn = sqlite3.connect("file:{db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute(
            "select id, name, key from channels where base_url like '%commandcode%' and status = 1 limit 1"
        )
        row = cursor.fetchone()
        if row and len(row) >= 3 and isinstance(row[2], str):
            key = row[2].strip()
    finally:
        conn.close()
except Exception:
    pass
print(json.dumps({{"key": key}}))
"""


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


def _flatten_key_items(items: Any) -> list[str]:
    """快取 list 可能是多行字串混雜：逐項再拆一次，去重保序。"""
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(items, list):
        return out
    for item in items:
        for key in _split_key_text(item) if isinstance(item, str) else []:
            if key not in seen:
                seen.add(key)
                out.append(key)
                if len(out) >= _MAX_KEYS:
                    return out
    return out


def _read_cached_keys(c_path: Path) -> list[str]:
    """讀快取：新格式 {"keys": [...]}，舊格式 {"key": "..."} 相容（都要再拆行）。"""
    try:
        if not c_path.is_file():
            return []
        data = json.loads(c_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    keys = _flatten_key_items(data.get("keys"))
    if keys:
        return keys
    return _split_key_text(data.get("key"))


def _write_cached_keys(c_path: Path, keys: list[str]) -> None:
    try:
        c_path.parent.mkdir(parents=True, exist_ok=True)
        iso = datetime.now(timezone.utc).isoformat()
        c_path.write_text(json.dumps({"keys": keys, "fetched_at": iso}), encoding="utf-8")
        c_path.chmod(0o600)
    except OSError:
        pass


def load_api_keys(
    env: dict | None = None,
    key_path: Path | str | None = None,
    runner: Any = None,
    cache_path: Path | str | None = None,
    ssh_host: str = NEWAPI_SSH_HOST,
    db_path: str = NEWAPI_DB_PATH,
) -> list[str]:
    """讀 CommandCode 的全部 API key，依序：環境變數 -> 本機檔 -> ssh 查 New API -> 讀快取。

    - 環境變數 COMMANDCODE_API_KEY 可用逗號或換行放多把
    - 本機檔 ~/.deskbar-agent/commandcode.key 每行一把
    - ssh 唯讀 New API：key 欄位按換行拆、去空行去重
    """
    env_dict = os.environ if env is None else env
    key = env_dict.get("COMMANDCODE_API_KEY")
    keys = _split_key_text(key) if isinstance(key, str) else []
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

    c_path = DEFAULT_CACHE_PATH if cache_path is None else Path(cache_path).expanduser()
    run_cmd = subprocess.run if runner is None else runner
    command = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        ssh_host,
        "python3", "-",
    ]
    ssh_keys: list[str] = []
    try:
        result = run_cmd(
            command,
            input=_newapi_remote_script(db_path),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if getattr(result, "returncode", 1) == 0:
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                raw = data.get("key")
                if raw is None:
                    raw = data.get("keys")
                if isinstance(raw, list):
                    ssh_keys = _flatten_key_items(raw)
                else:
                    ssh_keys = _split_key_text(raw)
    except Exception:
        ssh_keys = []

    if ssh_keys:
        _write_cached_keys(c_path, ssh_keys)
        return ssh_keys

    return _read_cached_keys(c_path)


def load_api_key(
    env: dict | None = None,
    key_path: Path | str | None = None,
    runner: Any = None,
    cache_path: Path | str | None = None,
    ssh_host: str = NEWAPI_SSH_HOST,
    db_path: str = NEWAPI_DB_PATH,
) -> str | None:
    """讀 CommandCode 的 API key（第一把，給舊呼叫者用）。"""
    keys = load_api_keys(
        env=env,
        key_path=key_path,
        runner=runner,
        cache_path=cache_path,
        ssh_host=ssh_host,
        db_path=db_path,
    )
    return keys[0] if keys else None


def parse_period_end(data: Any) -> datetime | None:
    """純函數：解析 subscriptions 回應的 data.currentPeriodEnd（ISO）。

    回 timezone-aware datetime；缺欄位／型別錯／解析失敗回 None。"""
    if not isinstance(data, dict):
        return None
    inner = data.get("data")
    if not isinstance(inner, dict):
        return None
    raw = inner.get("currentPeriodEnd")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_usage(data: Any) -> dict:
    """純函數：回傳 five_hour_pct, five_hour_resets_at, weekly_pct, weekly_resets_at, monthly_credits。
    百分比 = used / cap * 100（cap 為 0 或缺欄位時該視窗為 None）。
    resetAt 是 epoch 毫秒，轉為 timezone-aware UTC datetime。
    windowLimits.limited 為 false 或整段缺時各視窗為 None。
    exceeded 為 true 時仍照 used / cap 算。
    """
    out: dict[str, Any] = {
        "five_hour_pct": None,
        "five_hour_resets_at": None,
        "weekly_pct": None,
        "weekly_resets_at": None,
        "monthly_credits": None,
        "period_end": None,
    }
    if not isinstance(data, dict):
        return out

    credits = data.get("credits")
    if isinstance(credits, dict):
        monthly = credits.get("monthlyCredits")
        if monthly is not None and not isinstance(monthly, bool):
            try:
                out["monthly_credits"] = float(monthly)
            except (TypeError, ValueError):
                pass

    window_limits = data.get("windowLimits")
    if not isinstance(window_limits, dict) or not window_limits.get("limited", False):
        return out

    def _parse_window(entry: Any) -> tuple[float | None, datetime | None]:
        if not isinstance(entry, dict):
            return None, None
        used = entry.get("used")
        cap = entry.get("cap")
        pct = None
        if used is not None and cap is not None and not isinstance(used, bool) and not isinstance(cap, bool):
            try:
                u, c = float(used), float(cap)
                if c > 0:
                    pct = (u / c) * 100.0
            except (TypeError, ValueError):
                pass
        reset_raw = entry.get("resetAt")
        resets_at = None
        if reset_raw is not None and not isinstance(reset_raw, bool):
            try:
                ms = float(reset_raw)
                if ms > 0:
                    resets_at = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        return pct, resets_at

    out["five_hour_pct"], out["five_hour_resets_at"] = _parse_window(window_limits.get("fiveHour"))
    out["weekly_pct"], out["weekly_resets_at"] = _parse_window(window_limits.get("weekly"))
    return out


def parse_whoami(data: Any) -> dict:
    """純函數：解析 whoami 回應的 user.userName（name）與 user.id（account_id）。

    缺欄位／型別錯回 {"account_id": None, "name": ""}。"""
    out: dict[str, Any] = {"account_id": None, "name": ""}
    if not isinstance(data, dict):
        return out
    user = data.get("user")
    if not isinstance(user, dict):
        return out
    name = user.get("userName")
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()
    uid = user.get("id")
    if isinstance(uid, str) and uid.strip():
        out["account_id"] = uid.strip()
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
    """抓單一 CommandCode 帳號：whoami＋credits＋subscriptions。

    回 {"account_id", "name", "five_hour_pct", "five_hour_resets_at",
        "weekly_pct", "weekly_resets_at", "period_end", "monthly_credits"}；
    whoami 失敗（拿不到真的 account_id）回 None，避免用 key 前綴生出幽靈帳號；
    credits 401/403 或非 200 回 None。
    """
    if not isinstance(key, str) or not key.strip():
        return None
    key = key.strip()
    get = _get_client(http)
    if get is None:
        return None
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    identity: dict[str, Any] = {"account_id": None, "name": ""}
    try:
        whoami_response = get(WHOAMI_URL, headers=headers, timeout=15)
        if getattr(whoami_response, "status_code", None) == 200:
            try:
                parsed_identity = parse_whoami(whoami_response.json())
            except (ValueError, TypeError):
                parsed_identity = {"account_id": None, "name": ""}
            if parsed_identity.get("account_id"):
                identity["account_id"] = parsed_identity["account_id"]
            if parsed_identity.get("name"):
                identity["name"] = parsed_identity["name"]
    except Exception:
        pass
    try:
        response = get(USAGE_URL, headers=headers, timeout=15)
    except Exception as error:
        print(f"[CommandCode] 抓取失敗：{type(error).__name__}")
        return None
    status_code = getattr(response, "status_code", None)
    if status_code in (401, 403):
        print("[CommandCode] API key 被拒")
        return None
    if status_code != 200:
        print(f"[CommandCode] 抓取失敗：HTTP {status_code}")
        return None
    try:
        data = response.json()
    except (ValueError, TypeError):
        print("[CommandCode] 抓取失敗：回應不是合法 JSON")
        return None
    if identity["account_id"] is None:
        print("[CommandCode] whoami 失敗，略過這把 key（避免產生假帳號）")
        return None
    if not identity["name"]:
        identity["name"] = identity["account_id"]
    result = parse_usage(data)
    result["account_id"] = identity["account_id"]
    result["name"] = identity["name"]
    try:
        sub_response = get(SUBSCRIPTIONS_URL, headers=headers, timeout=15)
        if getattr(sub_response, "status_code", None) == 200:
            try:
                result["period_end"] = parse_period_end(sub_response.json())
            except (ValueError, TypeError):
                result["period_end"] = None
    except Exception:
        pass
    return result


def fetch_accounts(
    keys: list[str] | None = None,
    http: Any = None,
    env: dict | None = None,
    key_path: Path | str | None = None,
    runner: Any = None,
    cache_path: Path | str | None = None,
    ssh_host: str = NEWAPI_SSH_HOST,
    db_path: str = NEWAPI_DB_PATH,
) -> list[dict]:
    """逐把 key 呼叫 fetch_account，失敗的略過；回傳順序照 keys。"""
    if keys is None:
        keys = load_api_keys(
            env=env,
            key_path=key_path,
            runner=runner,
            cache_path=cache_path,
            ssh_host=ssh_host,
            db_path=db_path,
        )
    accounts: list[dict] = []
    for key in keys or []:
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            account = fetch_account(key, http=http)
        except Exception as error:
            print(f"[CommandCode] 抓取失敗：{type(error).__name__}")
            account = None
        if account is not None:
            accounts.append(account)
    return accounts


def fetch_usage(
    http: Any = None,
    env: dict | None = None,
    key_path: Path | str | None = None,
    runner: Any = None,
    cache_path: Path | str | None = None,
    ssh_host: str = NEWAPI_SSH_HOST,
    db_path: str = NEWAPI_DB_PATH,
) -> dict | None:
    """抓 CommandCode 用量（第一把 key；相容舊呼叫者）＝ fetch_account(第一把 key)。"""
    keys = load_api_keys(
        env=env,
        key_path=key_path,
        runner=runner,
        cache_path=cache_path,
        ssh_host=ssh_host,
        db_path=db_path,
    )
    if not keys:
        print("[CommandCode] 抓取失敗：找不到 API key")
        return None
    try:
        return fetch_account(keys[0], http=http)
    except Exception as error:
        print(f"[CommandCode] 抓取失敗：{type(error).__name__}")
        return None
