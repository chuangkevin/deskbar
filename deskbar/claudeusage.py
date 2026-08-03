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


# ---------------------------------------------------------------- 配速判定

# 各視窗長度（秒）：5 小時 session、7 天週限額、7 天 Fable 週限額
WINDOW_S = {"session": 5 * 3600, "weekly": 7 * 86400, "fable": 7 * 86400}
PACE_GRACE_PCT = 5.0     # 容許超前配速的緩衝（百分點）：視窗剛開的小額使用不該轉紅


def pace_pct(resets_at, now, window_s: float) -> "float | None":
    """視窗的時間進度 0..100＝此刻的「線性配速預算」：weekly 過了 2/7 的
    時間，配速就是 28.6%。resets_at 缺（agent 沒給）回 None。"""
    if resets_at is None:
        return None
    remaining = max(0.0, min(window_s, (resets_at - now).total_seconds()))
    return (1.0 - remaining / window_s) * 100.0


def over_pace(pct, resets_at, now, window_s: float) -> bool:
    """用量進度超過時間進度（含緩衝）＝燒太快，油表轉紅。"""
    p = pace_pct(resets_at, now, window_s)
    return pct is not None and p is not None and pct > p + PACE_GRACE_PCT


# ---------------------------------------------------------------- 忙/閒判定

BUSY_WINDOW_S = 20 * 60    # 最近 N 秒內 usage 有上升＝忙（也是轉閒的遲滯窗）
SCENE_AFTER_S = 20 * 60    # 連續忙滿 N 秒中欄才切場景（剛開工不急著換畫面）


class UsageActivity:
    """用 Claude usage 百分比的「上升」當使用者活動代理：在寫 code = usage
    在動。下降是視窗重置、不算活動；agent 沒推新資料（Mac 睡了/沒開）自然
    滑向閒。純邏輯吃單調秒數，不做 I/O。"""

    def __init__(self):
        self._pcts = None
        self._last_active: "float | None" = None
        self._busy_since: "float | None" = None

    def feed(self, info, mono: float) -> None:
        pcts = None if info is None else (info.session_pct, info.weekly_pct,
                                          info.fable_pct)
        if pcts is not None and self._pcts is not None:
            for new, old in zip(pcts, self._pcts):
                if new is not None and old is not None and new > old:
                    self._last_active = mono
                    break
        self._pcts = pcts
        if self.busy(mono):
            if self._busy_since is None:
                self._busy_since = mono
        else:
            self._busy_since = None

    def busy(self, mono: float) -> bool:
        return (self._last_active is not None
                and mono - self._last_active <= BUSY_WINDOW_S)

    def scene_ready(self, mono: float) -> bool:
        return (self.busy(mono) and self._busy_since is not None
                and mono - self._busy_since >= SCENE_AFTER_S)


def flow_target(scene_ready: bool, busy: bool, has_notes: bool) -> "str | None":
    """中欄自動排程的目標視圖（None＝不動）：
    - 忙滿門檻 → 場景（行事曆是噪音，給不索取注意力的畫面）
    - 忙但未滿 → 不動（剛開工，維持現狀）
    - 閒 → 便條牆優先（該看待辦的東西了），沒便條看行事曆
    迫近行程的搶焦點在 app 另一層，永遠壓過這裡。"""
    if scene_ready:
        return "scene"
    if busy:
        return None
    return "notes" if has_notes else "calendar"
