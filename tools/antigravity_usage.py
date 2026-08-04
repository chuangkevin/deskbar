"""Antigravity (Gemini) 用量抓取與推送工具。

為什麼不用 REST API：
Antigravity 額度 REST 端點 retrieveUserQuotaSummary 一律回傳 403 PERMISSION_DENIED
（已在 prod 與 daily 兩個 host 實測過）。唯一可行來源是用 pty 執行 agy TUI 的
/usage 命令並解析輸出。

執行方式與節奏：
透過 pty.fork() 執行 agy /usage 命令，此過程不消耗任何模型 token（純本地 TUI
與後端 RPC 查詢），但單次執行耗時約 45 秒。因此呼叫端排程節奏應為 5 分鐘一次
（300 秒），而非 60 秒。
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import struct
import termios
import time
from datetime import datetime, timedelta

import requests

AGY_BIN = os.environ.get("DESKBAR_AGY_BIN", "/Users/kevin/.local/bin/agy")


def strip_ansi(text: str) -> str:
    """去除 ANSI 控制碼與 terminal escape sequences。"""
    text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\][^\x07]*\x07', '', text)
    text = re.sub(r'\x1b[=>][0-9;]*[a-zA-Z]?', '', text)
    return text


def _parse_refresh_minutes(s: str) -> int | None:
    """解析倒數時間字串（例如 "164h 29m", "1h 29m", "29m", "2d 3h"）為總分鐘數。"""
    if not s:
        return None
    m = re.search(r'(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?', s.strip())
    if not m or not any(m.groups()):
        return None
    d = int(m.group(1)) if m.group(1) else 0
    h = int(m.group(2)) if m.group(2) else 0
    mins = int(m.group(3)) if m.group(3) else 0
    return d * 1440 + h * 60 + mins


def parse_usage_panel(text: str) -> dict[str, float | int | None]:
    """純函數：解析 /usage TUI 去掉 ANSI 之後的純文字。

    回傳字典格式：
    {
        "gemini_5h_remaining": 64.24, "gemini_5h_refresh_min": 89,
        "gemini_weekly_remaining": 94.04, "gemini_weekly_refresh_min": 9869
    }
    抓不到的鍵給 None。只解析 GEMINI MODELS 區塊，略過 CLAUDE AND GPT MODELS。
    任何格式不符一律回傳 None，不拋出例外。
    """
    res: dict[str, float | int | None] = {
        "gemini_5h_remaining": None,
        "gemini_5h_refresh_min": None,
        "gemini_weekly_remaining": None,
        "gemini_weekly_refresh_min": None,
    }
    if not text or not isinstance(text, str):
        return res

    try:
        idx = text.find("GEMINI MODELS")
        if idx == -1:
            return res

        sub = text[idx:]
        # 切到下一個全大寫組標題（如 CLAUDE AND GPT MODELS）
        m_next = re.search(r'\n([A-Z]{2,}(?:\s+[A-Z]{2,})+)', sub)
        if m_next:
            sub = sub[:m_next.start()]

        w_match = re.search(r'Weekly\s+Limit', sub, re.IGNORECASE)
        h5_match = re.search(r'(?:Five|5)\s+Hour\s+Limit', sub, re.IGNORECASE)

        w_block = ""
        h5_block = ""

        if w_match and h5_match:
            if w_match.start() < h5_match.start():
                w_block = sub[w_match.start():h5_match.start()]
                h5_block = sub[h5_match.start():]
            else:
                h5_block = sub[h5_match.start():w_match.start()]
                w_block = sub[w_match.start():]
        elif w_match:
            w_block = sub[w_match.start():]
        elif h5_match:
            h5_block = sub[h5_match.start():]

        if w_block:
            p_m = re.search(r'\]\s*(\d+\.\d+)%', w_block)
            if p_m:
                res["gemini_weekly_remaining"] = float(p_m.group(1))
            r_m = re.search(r'Refreshes\s+in\s+([^\n\r]+)', w_block)
            if r_m:
                res["gemini_weekly_refresh_min"] = _parse_refresh_minutes(r_m.group(1))

        if h5_block:
            p_m = re.search(r'\]\s*(\d+\.\d+)%', h5_block)
            if p_m:
                res["gemini_5h_remaining"] = float(p_m.group(1))
            r_m = re.search(r'Refreshes\s+in\s+([^\n\r]+)', h5_block)
            if r_m:
                res["gemini_5h_refresh_min"] = _parse_refresh_minutes(r_m.group(1))

    except Exception:
        pass

    return res


def fetch_usage_text(timeout_s: int = 60) -> str | None:
    """使用 pty.fork() 執行 agy 並發送 /usage 命令，取得純文字輸出。
    任何例外均回傳 None，不拋出例外。
    """
    if not os.path.exists(AGY_BIN):
        return None
    pid = -1
    fd = -1
    output = bytearray()
    try:
        pid, fd = pty.fork()
        if pid == 0:
            os.execv(AGY_BIN, [AGY_BIN])
    except Exception:
        return None

    try:
        # 必須設定 terminal winsize，否則 agy TUI 不會進行渲染
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))

        start_time = time.monotonic()
        # 等約 25 秒開機
        while time.monotonic() - start_time < 25:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                except OSError:
                    break

        # 寫入 /usage
        os.write(fd, b"/usage")
        time.sleep(1.5)
        os.write(fd, b"\r")

        # 再收 20 秒
        recv_start = time.monotonic()
        while time.monotonic() - recv_start < 20:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                except OSError:
                    break

        try:
            os.write(fd, b"\x03")
        except OSError:
            pass

    except Exception:
        pass
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if pid > 0:
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass

    if not output:
        return None

    raw_text = output.decode("utf-8", errors="ignore")
    return strip_ansi(raw_text)


def push_antigravity_usage(deskbar_url: str = "http://localhost:8080/api/usage",
                           token: str | None = None) -> None:
    """抓取 Antigravity usage、換算為用量百分比與 ISO8601 重置時間後 POST 推送到 deskbar。
    推送失敗只印出一行警告，不拋出例外。
    """
    text = fetch_usage_text()
    if not text:
        print("[antigravity_usage] 抓取 Antigravity usage 文字失敗（忽略，下一輪再試）")
        return

    parsed = parse_usage_panel(text)
    rem_5h = parsed.get("gemini_5h_remaining")
    ref_5h = parsed.get("gemini_5h_refresh_min")
    rem_wk = parsed.get("gemini_weekly_remaining")
    ref_wk = parsed.get("gemini_weekly_refresh_min")

    now = datetime.now().astimezone()

    ag_5h_pct = (100.0 - rem_5h) if rem_5h is not None else None
    ag_weekly_pct = (100.0 - rem_wk) if rem_wk is not None else None

    ag_5h_resets_at = (now + timedelta(minutes=ref_5h)).isoformat() if ref_5h is not None else None
    ag_weekly_resets_at = (now + timedelta(minutes=ref_wk)).isoformat() if ref_wk is not None else None

    payload = {
        "ag_5h_pct": ag_5h_pct,
        "ag_5h_resets_at": ag_5h_resets_at,
        "ag_weekly_pct": ag_weekly_pct,
        "ag_weekly_resets_at": ag_weekly_resets_at,
    }

    headers = {"X-Deskbar-Token": token} if token else {}
    try:
        resp = requests.post(deskbar_url, json=payload, headers=headers, timeout=5)
        if resp.status_code != 204:
            print(f"[antigravity_usage] deskbar 回應非預期：HTTP {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[antigravity_usage] 推送 deskbar 失敗（忽略）：{e}")
