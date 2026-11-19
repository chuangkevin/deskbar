"""tools/stale_alert.py：定時檢查 deskbar /api/usage，太久沒更新或連不上就發 Slack 告警。"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

STALE_ALL_SEC = 15 * 60
STALE_SECTION_SEC = 60 * 60
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
# 2026-11-20：檢查端（rpi-home）連 Pi 走 Tailscale，路徑剛切換時第一次連線會卡好幾秒；
# Slack 也遇過 MagicDNS 一時查不到 slack.com。單次失敗就發「連不上」是誤報，
# 所以抓用量與送 Slack 都重試幾次、中間隔一下，全部失敗才算數。
FETCH_TIMEOUT_S = 15
ATTEMPTS = 3
RETRY_WAIT_S = 20


def _log(msg: str) -> None:
    stamp = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}", file=sys.stderr)


def _with_retry(fn, attempts: int = ATTEMPTS, wait_s: float = RETRY_WAIT_S):
    """呼叫 fn()，回傳非 None／非 False 就停；全部失敗回傳最後一次的結果。"""
    result = None
    for i in range(attempts):
        result = fn()
        if result is not None and result is not False:
            return result
        if i < attempts - 1:
            time.sleep(wait_s)
    return result


def evaluate(payload: dict | None, now: datetime, prev: dict) -> tuple[dict, list[str]]:
    prev_problems = set(prev.get("problems", [])) if isinstance(prev, dict) else set()

    if payload is None:
        problems = {"down"}
        new_state = {"problems": sorted(problems)}
        messages = []
        if "down" not in prev_problems:
            messages.append("deskbar 連不上")
        return new_state, messages

    fetched_at_raw = payload.get("fetched_at")
    fetched_dt = None
    if fetched_at_raw is not None:
        try:
            if isinstance(fetched_at_raw, str):
                fetched_dt = datetime.fromisoformat(fetched_at_raw)
            elif isinstance(fetched_at_raw, (int, float)):
                fetched_dt = datetime.fromtimestamp(fetched_at_raw, tz=timezone.utc)
            elif isinstance(fetched_at_raw, datetime):
                fetched_dt = fetched_at_raw
        except Exception:
            fetched_dt = None

    if fetched_dt is not None and fetched_dt.tzinfo is None:
        fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
    now_cmp = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    is_stale = fetched_dt is None or (now_cmp - fetched_dt).total_seconds() > STALE_ALL_SEC

    if is_stale:
        problems = {"stale"}
        new_state = {"problems": sorted(problems)}
        messages = []
        if "stale" not in prev_problems:
            if fetched_dt is not None:
                minutes = int((now_cmp - fetched_dt).total_seconds() // 60)
                line1 = f"deskbar 用量 {minutes} 分鐘沒更新"
                line2 = f"最後資料 {fetched_dt.astimezone(TAIPEI_TZ).strftime('%H:%M')}"
            else:
                line1 = "deskbar 用量沒有資料時間"
                line2 = "最後資料 無"
            messages.append(f"{line1}\n{line2}")
        return new_state, messages

    problems = set()
    new_sections = []
    for sec in payload.get("sections") or []:
        key = sec.get("key")
        if not key:
            continue
        muted = bool(sec.get("muted", False))
        age_s = sec.get("age_s")
        if not isinstance(age_s, (int, float)) or isinstance(age_s, bool):
            continue
        if not muted and age_s > STALE_SECTION_SEC:
            prob = f"section:{key}"
            problems.add(prob)
            if prob not in prev_problems:
                new_sections.append(sec)

    new_state = {"problems": sorted(problems)}
    messages = []
    if new_sections:
        n = len(new_sections)
        titles = "、".join(str(s.get("title") or s.get("key")) for s in new_sections)
        messages.append(f"deskbar 有 {n} 區超過 1 小時沒更新\n{titles}")
    elif not problems and prev_problems:
        messages.append("deskbar 用量已恢復更新")

    return new_state, messages


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_path.with_name(f"{state_path.name}.tmp.{os.getpid()}")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, state_path)


def _send_slack_message(token: str, channel: str, text: str) -> bool:
    url = "https://slack.com/api/chat.postMessage"
    body = json.dumps({"channel": channel, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception as e:
        _log(f"Error sending Slack alert: {e}")
        return False


def _fetch_payload(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deskbar-stale-alert/1.0"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _log(f"fetch failed: {e}")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="deskbar stale alert")
    parser.add_argument("--url", default=os.environ.get("DESKBAR_ALERT_URL"))
    parser.add_argument("--token-file", default=os.environ.get("SLACK_TOKEN_FILE"))
    parser.add_argument("--user", default=os.environ.get("SLACK_ALERT_USER"))
    parser.add_argument("--state", default="~/.deskbar-stale-alert.json")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if not args.url:
        print("Error: missing --url (or DESKBAR_ALERT_URL)", file=sys.stderr)
        return 2

    token = None
    if not args.dry_run:
        if not args.token_file:
            print("Error: missing --token-file (or SLACK_TOKEN_FILE)", file=sys.stderr)
            return 2
        if not args.user:
            print("Error: missing --user (or SLACK_ALERT_USER)", file=sys.stderr)
            return 2

        token_path = Path(args.token_file).expanduser()
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception as e:
            print(f"Error reading token file {token_path}: {e}", file=sys.stderr)
            return 2

        if not token:
            print(f"Error: token file {token_path} is empty", file=sys.stderr)
            return 2

    payload = _with_retry(lambda: _fetch_payload(args.url))

    state_path = Path(args.state).expanduser()
    prev = {}
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    prev = data
        except Exception:
            prev = {}

    now = datetime.now(timezone.utc)
    new_state, messages = evaluate(payload, now, prev)

    if args.dry_run:
        for msg in messages:
            print(msg)
        _save_state(state_path, new_state)
        return 0

    for msg in messages:
        if not _with_retry(lambda: _send_slack_message(token, args.user, msg)):
            _log(f"Failed to send Slack message: {msg}")
            return 1
        _log(f"sent: {msg.splitlines()[0]}")

    _save_state(state_path, new_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
