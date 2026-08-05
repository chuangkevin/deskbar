from datetime import datetime, timezone
from typing import Any

import requests

METAR_URL = "https://aviationweather.gov/api/data/metar"
DEFAULT_STATION = "RCSS"      # 松山機場，離南港約 6 公里
STALE_AFTER_S = 5400          # METAR 超過 90 分鐘沒更新就視為不可用


def metar_to_code(wx_string: str | None, clouds: list[dict] | None,
                  visibility_m: float | int = 9999) -> int:
    """將 METAR 的天氣現象與雲量對應至 WMO weather code。

    2026-08-05 實測案例：數值預報模式（Open-Meteo）常在台北盆地午後對流時
    誤判局部微量降水（例如模式推算毛毛雨 Code 53，但現場地面完全乾燥）。
    本函數將實測觀測對應成既有 WMO 代碼，讓 UI 與場景系統無縫對接。

    對應順序由強至弱，第一個命中即回傳。
    """
    wx = (wx_string or "").upper()

    # 天氣現象比對（強至弱）
    if "TS" in wx:
        return 95
    if "SN" in wx:
        return 73
    # SHRA 包含 RA，因此 SH 必須排在 RA 前面判斷，避免將陣雨錯判為普通雨
    if "SHRA" in wx or "SH" in wx:
        return 81
    if "DZ" in wx:
        return 53
    if "RA" in wx:
        return 63
    if "FG" in wx:
        return 45
    if "BR" in wx and visibility_m < 5000:
        return 45

    # 無天氣現象時依雲量等級判斷（取所有雲層中最高的覆蓋率）
    max_code = 0
    if clouds and isinstance(clouds, list):
        for c in clouds:
            if isinstance(c, dict):
                cover = str(c.get("cover", "")).upper()
                if cover in ("OVC", "BKN"):
                    code = 3
                elif cover == "SCT":
                    code = 2
                elif cover == "FEW":
                    code = 1
                else:
                    code = 0
                if code > max_code:
                    max_code = code

    return max_code


def parse_metar_json(body: Any) -> dict | None:
    """解析 aviationweather.gov format=json 回傳的 JSON list。

    2026-08-05 實測案例：極端對流雨常造成內插推估失真，故解析 NOAA 氣象站實測 JSON。
    欄位缺失或格式異常時優雅回傳 None，確保不中斷天氣同步流程。
    """
    if not isinstance(body, list) or not body:
        return None
    item = body[0]
    if not isinstance(item, dict):
        return None

    try:
        temp = float(item["temp"])
        raw_time = item["reportTime"]
        if not isinstance(raw_time, str):
            return None
        observed_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        wx_string = item.get("wxString")
        clouds = item.get("clouds")

        raw_visib = item.get("visib")
        try:
            visib_m = float(raw_visib)
        except (TypeError, ValueError):
            visib_m = 9999.0

        code = metar_to_code(wx_string, clouds, visib_m)
        raw_ob = item.get("rawOb") or item.get("raw") or ""

        return {
            "temp": temp,
            "code": code,
            "observed_at": observed_at,
            "raw": str(raw_ob),
        }
    except Exception:
        return None


def fetch_metar(station: str = DEFAULT_STATION, http_get=requests.get) -> dict | None:
    """向 NOAA aviationweather.gov 抓取指定氣象站 METAR 實測。

    2026-08-05 實測案例：台北松山機場（RCSS）離市區極近，以實測代替 Open-Meteo 現況。
    為避免政府 API 擋空 User-Agent，固定帶入 deskbar/1.0 標頭。
    任何網路/解析例外一律優雅回傳 None。
    """
    if not station:
        return None
    try:
        resp = http_get(
            METAR_URL,
            params={"ids": station, "format": "json"},
            headers={"User-Agent": "deskbar/1.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return parse_metar_json(resp.json())
    except Exception:
        return None
