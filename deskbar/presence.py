from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from deskbar.presence_probes import (
    BLE_PROBE_TIMEOUT_S,
    BLE_SCAN_SECONDS,
    PROBE_TIMEOUT_S,
    _MAC_RE,
    _PROBE_LOCK,
    _RSSI_RE,
    _time,
    adapter_healthy,
    mac_to_dbus_path,
    parse_dbus_rssi,
    probe_ble_once,
    probe_once,
    try_recover_adapter,
)

if TYPE_CHECKING:
    from deskbar.config import Settings
    from deskbar.store import AppState

TZ = ZoneInfo("Asia/Taipei")

PROBE_BACKOFF_S = (0, 0, 30, 60, 120, 300, 600, 1800)
# 2026-08-10 實機證據：BLE 是純接收、不建立連線，失敗只代表「現在掃不到」，
# 沒有累積傷害；退避只需避免探測重疊，若拉到 30 分鐘會讓使用者回座後很久才被偵測到。
BLE_BACKOFF_S = (0, 0, 15, 30, 60, 90, 120)
RECOVERY_AFTER_FAILS = 3      # 連續失敗幾次才檢查控制器健康
RECOVERY_RECHECK_EVERY_FAILS = 3  # 第一次檢查後，每 N 次失敗再重查一次
UNHEALTHY_RECHECK_S = 1800    # 控制器不健康、停止探測時，每 30 分鐘重試一次健康檢查
UNHEALTHY_RECHECK_BLE_S = 300  # BLE 不建立連線，控制器不健康時縮短重查，避免無謂卡住 30 分鐘

BLE_MIN_INTERVAL_S = 45       # BLE 模式的最小輪詢間隔（必須大於 probe timeout）


def backoff_delay(fail_streak: int, source: str = "bluetooth") -> int:
    """連續 fail_streak 次探測失敗後，除了正常間隔還要「額外」等幾秒。
    bluetooth：fail_streak<=0 → 0；1 → 0（第一次失敗不罰，可能只是抖動）；
    2→30、3→60、4→120、5→300、6→600、7 以上→1800（封頂）。BLE 則封頂 120 秒。

    2026-08-05 實機事故教訓：探測是「主動建立連線」（l2ping 會建立 ACL 連線），
    而不是被動偵測。使用者帶著手機離開後，對不存在的裝置每一次嘗試探測都是一次硬體風險。
    在 Pi Zero 2W 的 BCM43438 晶片上，懸掛的 pending 連線堆積會導致藍牙控制器停止回應
    HCI 指令（dmesg 出現 command 0x0406 tx timeout, Opcode 0x200b / 0x0c03 failed: -110），
    甚至連 HCI_Reset 都超時卡死，最終整顆晶片死鎖只能重開機。
    因此手機不在場時必須盡量少探，退避上限拉高至 1800 秒（30 分鐘），將曝險比之前再降 3 倍。
    """
    if fail_streak <= 0:
        return 0
    backoff = BLE_BACKOFF_S if source == "ble" else PROBE_BACKOFF_S
    return backoff[min(fail_streak, len(backoff) - 1)]


def next_sleep(interval_sec: int, fail_streak: int, source: str = "bluetooth") -> int:
    """這一輪結束後要睡幾秒＝正常間隔＋退避。純函數，方便測試。"""
    return interval_sec + backoff_delay(fail_streak, source=source)


def should_check_adapter_health(fail_streak: int) -> bool:
    """連續探測失敗時，何時要檢查藍牙 adapter 是否還健康。

    舊版只在 fail_streak == 3 檢查一次；實機 BLE 離席觀察到 fail_streak 可累到
    300+，若控制器在第 4 次之後才壞，就永遠不會進復原流程。改成第 3 次先查，
    之後每 RECOVERY_RECHECK_EVERY_FAILS 次再查一次。
    """
    return fail_streak >= RECOVERY_AFTER_FAILS and (
        (fail_streak - RECOVERY_AFTER_FAILS) % RECOVERY_RECHECK_EVERY_FAILS == 0
    )


def should_log_backoff(fail_streak: int, interval_sec: int,
                       source: str = "bluetooth") -> bool:
    """退避 log 節流。

    長時間離席是正常狀態，不能每輪都刷 journal；但初期與整數節點要保留，方便
    對照 kernel Bluetooth / Wi-Fi 事件。
    """
    delay = backoff_delay(fail_streak, source=source)
    if delay <= interval_sec * 2:
        return False
    return fail_streak <= 6 or fail_streak % 10 == 0


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
                          settings_lock: threading.Lock, interval: int = 45,
                          runner=subprocess.run) -> bool:
    """啟動在場感應背景執行緒。**永遠啟動**：迴圈每輪自己檢查
    enabled/mac/source，沒開或非感應狀態就 no-op 睡下一輪——2026-07-27 首日教訓。

    支援三種在場來源（2026-08-04 主動 ACL 擴充 / 2026-08-06 被動 BLE 擴充）：
    1. bluetooth：藍牙 l2ping/hcitool 主動連線探測。配合 fail_streak 退避保護控制器。
       2026-08-05 事故防禦：fail_streak 達到 RECOVERY_AFTER_FAILS (3) 時檢查
       adapter_healthy() 並嘗試 try_recover_adapter()。若復原失敗則進入
       停止探測狀態（UNHEALTHY_RECHECK_S=1800s 重新檢查健康度），並將在場狀態設為 False。
    2. ble：藍牙被動 BLE 掃描探測（bluetoothctl scan on + info <MAC>）。
       2026-08-06 實機驗證：不建立 ACL 連線，靠 IRK 解析輪替 MAC，根治連線懸掛死鎖；
       單次探測最長 20 秒，輪詢間隔下限強制為 BLE_MIN_INTERVAL_S (45 秒) 以免重疊。
       晶片健康檢查與復原機制仍保留；退避改用無累積硬體傷害的 BLE 短版。
    3. push：外部 POST /api/presence 主動推送。本執行緒不作藍牙探測，
       僅檢查 expire_push() 超過 ttl_s 自動收回私人行事曆。
    """

    def loop():
        fail_streak = 0
        stopped_probing = False

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
                    stopped_probing = False
                    prev = state.snapshot().presence
                    state.set_presence(replace(prev, enabled=False))
                    sleep_time = interval_now
                elif source_now == "push":
                    fail_streak = 0
                    stopped_probing = False
                    prev = state.snapshot().presence
                    now = datetime.now(TZ)
                    new = expire_push(prev, now, push_ttl_now)
                    state.set_presence(replace(new, enabled=True))
                    sleep_time = interval_now
                elif mac_now:
                    # 2026-08-06 被動 BLE 掃描 vs 傳統 ACL l2ping 探測
                    # BLE 模式單次探測最長需 20 秒 (BLE_PROBE_TIMEOUT_S)，
                    # 實際睡眠時間強制套用 max(interval_now, BLE_MIN_INTERVAL_S) 以免探測重疊；
                    # 探測與復原邏輯與傳統藍牙模式完全一致。
                    if source_now == "ble":
                        effective_interval = max(interval_now, BLE_MIN_INTERVAL_S)
                        probe_fn = lambda m: probe_ble_once(m, runner=runner)
                    else:
                        effective_interval = interval_now
                        probe_fn = lambda m: probe_once(m, runner=runner)
                    unhealthy_recheck = (
                        UNHEALTHY_RECHECK_BLE_S if source_now == "ble"
                        else UNHEALTHY_RECHECK_S
                    )

                    if stopped_probing:
                        if adapter_healthy(runner=runner):
                            print("[presence] 藍牙控制器已恢復健康，自動恢復藍牙探測")
                            stopped_probing = False
                            fail_streak = 0
                            present_probe, rssi = probe_fn(mac_now)
                            if present_probe:
                                fail_streak = 0
                            else:
                                fail_streak += 1
                            prev = state.snapshot().presence
                            now = datetime.now(TZ)
                            new = decide(present_probe, rssi, threshold, prev, now, grace)
                            state.set_presence(replace(new, enabled=True))
                            sleep_time = next_sleep(effective_interval, fail_streak, source=source_now)
                            if should_log_backoff(fail_streak, effective_interval,
                                                  source=source_now):
                                print(f"[presence] 探測退避：fail_streak={fail_streak}，"
                                      f"sleep_seconds={sleep_time}，source={source_now}")
                        else:
                            prev = state.snapshot().presence
                            state.set_presence(replace(prev, present=False, rssi=None, enabled=True))
                            sleep_time = unhealthy_recheck
                    else:
                        present_probe, rssi = probe_fn(mac_now)
                        if present_probe:
                            fail_streak = 0
                        else:
                            fail_streak += 1
                            if should_check_adapter_health(fail_streak):
                                if not adapter_healthy(runner=runner):
                                    print("[presence] 藍牙控制器不健康，嘗試自動復原...")
                                    if try_recover_adapter(runner=runner):
                                        print("[presence] 藍牙控制器自動復原成功，重置連續失敗計數")
                                        fail_streak = 0
                                    else:
                                        print("[presence] 藍牙控制器自動復原失敗，進入停止探測狀態")
                                        stopped_probing = True

                        prev = state.snapshot().presence
                        now = datetime.now(TZ)
                        if stopped_probing:
                            state.set_presence(replace(prev, present=False, rssi=None, enabled=True))
                            sleep_time = unhealthy_recheck
                        else:
                            new = decide(present_probe, rssi, threshold, prev, now, grace)
                            state.set_presence(replace(new, enabled=True))
                            sleep_time = next_sleep(effective_interval, fail_streak, source=source_now)
                            if should_log_backoff(fail_streak, effective_interval,
                                                  source=source_now):
                                print(f"[presence] 探測退避：fail_streak={fail_streak}，"
                                      f"sleep_seconds={sleep_time}，source={source_now}")
                else:
                    fail_streak = 0
                    stopped_probing = False
                    prev = state.snapshot().presence
                    state.set_presence(replace(prev, enabled=False))
                    sleep_time = interval_now

                _time.sleep(sleep_time)
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
