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

PROBE_TIMEOUT_S = 5        # 既有 subprocess timeout，抽成常量（原本硬寫在 probe_once）
PROBE_BACKOFF_S = (0, 0, 30, 60, 120, 300, 600)
_PROBE_LOCK = threading.Lock()


def backoff_delay(fail_streak: int) -> int:
    """連續 fail_streak 次探測失敗後，除了正常間隔還要「額外」等幾秒。
    fail_streak<=0 → 0；1 → 0（第一次失敗不罰，可能只是抖動）；
    2→30、3→60、4→120、5→300、6 以上→600（封頂）。

    2026-08-04 實機事故教訓：探測失敗代表控制器層（如 Pi Zero 2W 的 BCM43438）
    可能已經有清不掉的 pending 連線請求，繼續按原間隔硬打會把藍牙控制器打到不回
    HCI 指令（dmesg 出現 tx timeout, HCI_Reset opcode failed），最終整顆晶片死鎖。
    因此失敗時必須指數退避，保護硬體不被連續 request 灌爆。
    """
    if fail_streak <= 0:
        return 0
    return PROBE_BACKOFF_S[min(fail_streak, len(PROBE_BACKOFF_S) - 1)]


def next_sleep(interval_sec: int, fail_streak: int) -> int:
    """這一輪結束後要睡幾秒＝正常間隔＋退避。純函數，方便測試。"""
    return interval_sec + backoff_delay(fail_streak)


def expire_push(prev: PresenceState, now: datetime, ttl_s: int) -> PresenceState:
    """push 模式的唯一狀態轉換：last_seen 超過 ttl_s 沒更新就轉為不在場。
    last_seen 為 None → 不在場。已經是不在場就原樣回傳。
    這是隱私保證：手機端的捷徑掛掉時，私人行事曆必須自己收回去，
    不能因為沒人再推就永遠留在「在場」。
    """
    if not prev.present:
        return prev
    if prev.last_seen is None:
        return replace(prev, present=False)
    if (now - prev.last_seen).total_seconds() >= ttl_s:
        return replace(prev, present=False)
    return prev


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
    3. 2026-08-04 實機事故保險：同時只允許一個 probe 在跑。若上一輪 l2ping
       還卡在 kernel 或 BCM43438 晶片層沒收乾淨，拿不到 _PROBE_LOCK 就立刻
       放棄並回 (False, None)，絕不在控制器上再疊一層 pending 連線。
    """
    if not _PROBE_LOCK.acquire(blocking=False):
        return False, None

    try:
        try:
            ping = runner(["l2ping", "-c1", "-t2", mac], capture_output=True,
                          text=True, timeout=PROBE_TIMEOUT_S)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False, None
        if ping.returncode != 0:
            return False, None

        rssi = None
        try:
            rssi_proc = runner(["hcitool", "rssi", mac], capture_output=True,
                               text=True, timeout=PROBE_TIMEOUT_S)
            if rssi_proc.returncode == 0:
                m = _RSSI_RE.search(rssi_proc.stdout or "")
                if m:
                    rssi = int(m.group())
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            rssi = None
        return True, rssi
    finally:
        _PROBE_LOCK.release()


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
    """啟動在場感應背景執行緒。**永遠啟動**：迴圈每輪自己檢查
    enabled/mac/source，沒開或非感應狀態就 no-op 睡下一輪——2026-07-27 首日教訓。

    支援兩種在場來源（2026-08-04 實機事故擴充）：
    1. bluetooth：藍牙 l2ping/hcitool 探測。配合 fail_streak 退避保護控制器。
    2. push：外部 POST /api/presence 主動推送。本執行緒不作藍牙探測，
       僅檢查 expire_push() 超過 ttl_s 自動收回私人行事曆。
    """

    def loop():
        fail_streak = 0
        while True:
            try:
                with settings_lock:
                    mac_now = settings.presence_mac
                    threshold = settings.presence_rssi_threshold
                    grace = settings.presence_grace_sec
                    enabled_now = settings.presence_enabled
                    interval_now = getattr(settings, "presence_interval_sec", interval)
                    source_now = getattr(settings, "presence_source", "bluetooth")
                    push_ttl_now = getattr(settings, "presence_push_ttl_sec", 900)

                if not enabled_now:
                    fail_streak = 0
                    prev = state.snapshot().presence
                    state.set_presence(replace(prev, enabled=False))
                elif source_now == "push":
                    fail_streak = 0
                    prev = state.snapshot().presence
                    now = datetime.now(TZ)
                    new = expire_push(prev, now, push_ttl_now)
                    state.set_presence(replace(new, enabled=True))
                elif mac_now:
                    present_probe, rssi = probe_once(mac_now)
                    if present_probe:
                        fail_streak = 0
                    else:
                        fail_streak += 1
                    prev = state.snapshot().presence
                    now = datetime.now(TZ)
                    new = decide(present_probe, rssi, threshold, prev, now, grace)
                    state.set_presence(replace(new, enabled=True))
                else:
                    fail_streak = 0
                    prev = state.snapshot().presence
                    state.set_presence(replace(prev, enabled=False))

                _time.sleep(next_sleep(interval_now, fail_streak))
            except Exception:
                _time.sleep(interval)

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
