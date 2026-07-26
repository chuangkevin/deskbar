"""Claude Code usage（用量）資料型別：純資料層，不做任何網路呼叫。

背景：裝置端自行做 OAuth PKCE 登入這條路已被驗證會被 Cloudflare 擋（403 code
1010）與 token endpoint 帳號級限流（429），列為否決方案（見 claude-usage-cube
專案的驗證結果）。改成「Mac 上常駐的 agent 每 60 秒讀本機 macOS Keychain 的
Claude Code 憑證、打官方 usage API，再主動 POST 推給這台裝置」——deskbar 這端
只被動接收（見 deskbar.webserver 的 POST /api/usage），不再持有任何憑證、
不再對外發出任何請求。

這支模組因此只剩兩樣東西：
- UsageInfo：usage 快照的資料形狀（session/weekly/fable 三組百分比＋重置時間，
  外加 fetched_at 供油表判斷資料新鮮度）。
- fmt_countdown：把「距某個時間點還有多久」格式成人看得懂的字串，油表渲染與
  舊版都共用的純函數，跟資料來源無關所以留在這裡。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UsageInfo:
    session_pct: float | None
    session_resets_at: datetime | None
    weekly_pct: float | None
    weekly_resets_at: datetime | None
    fable_pct: float | None
    fable_resets_at: datetime | None
    fetched_at: datetime


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
