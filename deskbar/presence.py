from __future__ import annotations

import re
import subprocess
import threading
import time as _time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from deskbar.config import Settings
    from deskbar.store import AppState

TZ = ZoneInfo("Asia/Taipei")
_RSSI_RE = re.compile(r"-?\d+")


@dataclass(frozen=True)
class PresenceState:
    present: bool
    rssi: int | None
    last_seen: datetime | None
    enabled: bool


def probe_once(mac: str, runner=subprocess.run) -> tuple[bool, int | None]:
    """探測一次藍牙裝置是否在場。跑在背景執行緒裡，任何失敗都不得拋例外，
    否則整條 thread 會悶死、之後永遠不再探測：

    1. l2ping -c1 -t2：送一個 ping、逾時 2 秒，回應成功（returncode 0）視為在場。
       指令不存在（環境沒裝 bluez-utils）或逾時，一律當作「不在場、無 RSSI」。
    2. 在場才進一步用 hcitool rssi 取信號強度；同樣容錯，取不到就回 None，
       不影響「在場」這個判定本身（RSSI 只是輔助門檻，見 decide()）。
    """
    try:
        ping = runner(["l2ping", "-c1", "-t2", mac], capture_output=True,
                      text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, None
    if ping.returncode != 0:
        return False, None

    rssi = None
    try:
        rssi_proc = runner(["hcitool", "rssi", mac], capture_output=True,
                           text=True, timeout=5)
        if rssi_proc.returncode == 0:
            m = _RSSI_RE.search(rssi_proc.stdout or "")
            if m:
                rssi = int(m.group())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        rssi = None
    return True, rssi


def decide(present_probe: bool, rssi: int | None, threshold: int, prev: PresenceState,
          now: datetime, grace_sec: int) -> PresenceState:
    """純函數，不做任何 I/O：依本輪探測結果與上一輪狀態算出新的 PresenceState。

    - 探測成功且 RSSI 過門檻（rssi 為 None，即取不到訊號強度時不因此判定不在場；
      或 rssi >= threshold）→ 判定在場，last_seen 更新為 now。
    - 否則（沒探測到裝置，或 RSSI 太弱）→ 防抖：若已有 last_seen 且
      now - last_seen 尚未超過 grace_sec 秒，維持在場（人剛好走出訊號範圍，
      不該立刻鎖住畫面）；超過寬限才判定不在場。last_seen 在這個分支不更新。
    """
    if present_probe and (rssi is None or rssi >= threshold):
        return PresenceState(present=True, rssi=rssi, last_seen=now, enabled=prev.enabled)
    if prev.last_seen is not None and (now - prev.last_seen).total_seconds() < grace_sec:
        return PresenceState(present=True, rssi=rssi, last_seen=prev.last_seen,
                             enabled=prev.enabled)
    return PresenceState(present=False, rssi=rssi, last_seen=prev.last_seen,
                         enabled=prev.enabled)


def start_presence_thread(state: "AppState", settings: "Settings",
                          settings_lock: threading.Lock, interval: int = 45) -> bool:
    """啟動藍牙在場感應背景執行緒。**永遠啟動**：迴圈每輪自己檢查
    enabled/mac，沒開就 no-op 睡下一輪——2026-07-27 首日教訓：開機時
    presence_mac 還沒設就不建 thread，之後使用者在藍牙配對頁配好裝置、
    打開開關，功能卻要重開機才活，看起來就是「開了沒反應」。

    迴圈每輪：持 settings_lock 只做快照讀取（mac/threshold/grace/enabled/間隔，
    純量、很快)，放鎖後才做探測（l2ping/hcitool，可能耗時到秒級，不該卡住其他
    也要拿 settings_lock 的執行緒——呼應 sync.py 同樣的鎖範圍原則）。探測完依
    decide() 算出新狀態，再用當輪讀到的 enabled 覆寫 enabled 欄位，最後
    state.set_presence(...) 寫回。
    """

    def loop():
        while True:
            with settings_lock:
                mac_now = settings.presence_mac
                threshold = settings.presence_rssi_threshold
                grace = settings.presence_grace_sec
                enabled_now = settings.presence_enabled
                # 每輪重讀：設定頁「感應速度」改了間隔要立刻生效，不用重開機
                interval_now = getattr(settings, "presence_interval_sec", interval)
            if enabled_now and mac_now:
                present_probe, rssi = probe_once(mac_now)
                prev = state.snapshot().presence
                now = datetime.now(TZ)
                new = decide(present_probe, rssi, threshold, prev, now, grace)
                state.set_presence(replace(new, enabled=True))
            else:
                prev = state.snapshot().presence
                state.set_presence(replace(prev, enabled=False))
            _time.sleep(interval_now)

    threading.Thread(target=loop, daemon=True).start()
    return True


# ---------------------------------------------------------------- 久坐提示

SEDENTARY_AFTER_S = 60 * 60   # 連續在座滿 60 分鐘 → 提示
SEDENTARY_HINT_S = 180        # 提示顯示 3 分鐘後自行消失
SEDENTARY_GAP_S = 5 * 60      # 短於 5 分鐘的離席（倒水/印表機）不算休息、不重置


class SedentaryTracker:
    """久坐追蹤（純邏輯、吃單調秒數，不做 I/O）：連續在座滿 SEDENTARY_AFTER_S
    出提示，顯示 SEDENTARY_HINT_S 後收起並重新起算下一輪——自然形成約每小時
    一次的節奏。離席超過 SEDENTARY_GAP_S 才算真的休息（重置計時、收回提示）；
    更短的離開視為感應抖動或倒個水。在場來源是手機藍牙 RSSI，本質是「手機在
    桌上」的代理——人起身通常帶手機，夠用。"""

    def __init__(self):
        self._sit_start: "float | None" = None
        self._gap_start: "float | None" = None
        self._hint_until = 0.0

    def reset(self) -> None:
        self._sit_start = None
        self._gap_start = None
        self._hint_until = 0.0

    def update(self, present: bool, now: float) -> None:
        if present:
            self._gap_start = None
            if self._sit_start is None:
                self._sit_start = now
            elif now - self._sit_start >= SEDENTARY_AFTER_S:
                self._hint_until = now + SEDENTARY_HINT_S
                self._sit_start = now          # 下一輪從提示起算
        else:
            if self._gap_start is None:
                self._gap_start = now
            elif now - self._gap_start >= SEDENTARY_GAP_S:
                self.reset()                   # 真的離座：計時與提示都收掉

    def hint_active(self, now: float) -> bool:
        return now < self._hint_until
