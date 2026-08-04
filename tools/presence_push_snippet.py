"""貼進外部服務或自動化腳本的函數：把在場狀態推送到 deskbar 的 POST /api/presence。

背景（2026-08-04 實機事故擴充）：
iPhone 不回應 L2CAP echo 且 BLE MAC 地址隨機化，藍牙主動探測對 iPhone 本質不可靠；
且頻繁對未配對裝置 probe 會導致 Pi Zero 2W BCM43438 晶片 deadlocks。
改用「推送式在場」——由 iPhone 捷徑（Shortcuts）或 Mac 腳本在連上 Wi-Fi／到達指定地點時
主動推送 status 給 deskbar。deskbar 僅被動接收，且過期自動收回。

iOS 捷徑（Shortcuts）個人自動化設定指引：
1. 自動化觸發條件：
   - 「當連上指定 Wi-Fi」（例如 Home Wi-Fi）或「到達指定地點（家/辦公室）」
   - 離開時設定對應的離開自動化
2. 動作步驟：
   - 新增「取得 URL 內容」（Get Contents of URL）
   - URL: http://<deskbar-ip>:8080/api/presence (或 Tailnet 網址)
   - 方法: POST
   - 標頭: X-Deskbar-Token: <token> (若 deskbar 有設定 DESKBAR_PUSH_TOKEN)
   - 要求主體 (Request Body): JSON
   - 欄位: {"present": true}  (離開自動化則推 {"present": false})

payload 欄位規則（deskbar 端會驗證，格式不對回 400）：
    present : 必填 bool (True / False)
    rssi    : 選填 int，或 None (例如 -65)

推送失敗（網路問題、deskbar 沒開機…）只印一行警告，不拋例外。
"""
from __future__ import annotations

import requests


def push_presence(present: bool, rssi: int | None = None,
                  url: str = "http://deskbar.local:8080/api/presence",
                  token: str | None = None) -> None:
    headers = {"X-Deskbar-Token": token} if token else {}
    payload = {"present": present}
    if rssi is not None:
        payload["rssi"] = rssi

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
    except requests.RequestException as e:
        print(f"[presence_push] 推送 deskbar 失敗（忽略，下一輪再試）：{e}")
        return
    if resp.status_code != 204:
        print(f"[presence_push] deskbar 回應非預期：HTTP {resp.status_code} {resp.text[:200]}")
