"""貼進既有 usage agent（例如 claude-usage-cube/agent/cube_agent.py）的一個
函數：把讀好的 Claude Code usage 推送到 deskbar 的 POST /api/usage。

背景：裝置端自己做 OAuth PKCE 登入這條路已驗證會被 Cloudflare 擋（403 code
1010）與 token endpoint 帳號級限流（429），列為否決方案。改成「Mac 上的
agent 每 60 秒讀本機 Keychain 的 Claude Code 憑證、打官方 usage API，主動推
給 deskbar」——deskbar 本身只被動接收，不再持有任何憑證。

用法：把 push_to_deskbar() 整個函數複製貼進你的 agent，讀完 usage 之後呼叫一次：

    push_to_deskbar(
        {
            "session_pct": 42.0,
            "session_resets_at": "2026-07-27T18:00:00+00:00",
            "weekly_pct": 61.5,
            "weekly_resets_at": "2026-08-02T00:00:00+00:00",
            "fable_pct": 12.0,          # 沒有這筆資料就給 None（缺的欄位一律可以是 None）
            "fable_resets_at": None,
        },
        url="http://deskbar.local:8080/api/usage",
        token=None,   # 若 Pi 上設了 DESKBAR_PUSH_TOKEN 環境變數，這裡要帶同樣的字串
    )

payload 欄位規則（deskbar 端會驗證，格式不對回 400）：
    session_pct / weekly_pct / fable_pct           ：0~100 的數字，或 None
    session_resets_at / weekly_resets_at / fable_resets_at ：ISO8601 字串，或 None

推送失敗（網路問題、deskbar 沒開機…）只印一行警告，不拋例外——不該讓 usage
推送失敗中斷 agent 的主流程（BLE 寫入、下一輪排程等）。
"""
from __future__ import annotations

import requests


def push_to_deskbar(usage_dict: dict, url: str, token: str | None = None) -> None:
    headers = {"X-Deskbar-Token": token} if token else {}
    try:
        resp = requests.post(url, json=usage_dict, headers=headers, timeout=5)
    except requests.RequestException as e:
        print(f"[usage_push] 推送 deskbar 失敗（忽略，下一輪再試）：{e}")
        return
    if resp.status_code != 204:
        print(f"[usage_push] deskbar 回應非預期：HTTP {resp.status_code} {resp.text[:200]}")
