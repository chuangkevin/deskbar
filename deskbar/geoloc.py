"""IP 定位：把「當前位置」跟著裝置的對外 IP 走。

deskbar 沒有 GPS——但它插在哪個網路，就在哪個城市。搬機器（家↔公司）
換網路後，下一輪天氣同步自動跟上新位置，不用進設定改座標（2026-07-30
需求：「我要他取得的是我當前位置的天氣資訊」）。

用 ip-api.com 免金鑰、lang=zh-TW 直接回中文城市名（「台北」而不是
"Taipei"，左欄是中文介面）。免費層只有 http——這查詢本來就是「用自己的
IP 問自己在哪」，內容無祕密；最壞情況是被路徑上的人竄改座標，影響僅止於
天氣顯示錯城市，風險可接受。失敗一律回 None（保留原設定），定位是加分項，
永遠不擋天氣同步本身。
"""
from __future__ import annotations

import requests

URL = "http://ip-api.com/json/"
_PARAMS = {"lang": "zh-TW", "fields": "status,lat,lon,city,regionName"}


def locate(http_get=requests.get) -> "tuple[float, float, str] | None":
    """回 (lat, lon, label)；label 取城市名（沒有就用行政區名），截 12 字。"""
    try:
        d = http_get(URL, params=_PARAMS, timeout=10).json()
        if d.get("status") != "success":
            return None
        lat, lon = float(d["lat"]), float(d["lon"])
        label = str(d.get("city") or d.get("regionName") or "").strip()
        return lat, lon, (label[:12] or "目前位置")
    except Exception:
        return None
