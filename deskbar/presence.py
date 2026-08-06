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
PROBE_BACKOFF_S = (0, 0, 30, 60, 120, 300, 600, 1800)
_PROBE_LOCK = threading.Lock()
RECOVERY_AFTER_FAILS = 3      # 連續失敗幾次才檢查控制器健康
UNHEALTHY_RECHECK_S = 1800    # 控制器不健康、停止探測時，每 30 分鐘重試一次健康檢查

BLE_SCAN_SECONDS = 8          # 單次掃描視窗
BLE_PROBE_TIMEOUT_S = 20      # 整個 bluetoothctl 子行程的上限
BLE_MIN_INTERVAL_S = 45       # BLE 模式的最小輪詢間隔（必須大於 probe timeout）
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def backoff_delay(fail_streak: int) -> int:
    """連續 fail_streak 次探測失敗後，除了正常間隔還要「額外」等幾秒。
    fail_streak<=0 → 0；1 → 0（第一次失敗不罰，可能只是抖動）；
    2→30、3→60、4→120、5→300、6→600、7 以上→1800（封頂）。

    2026-08-05 實機事故教訓：探測是「主動建立連線」（l2ping 會建立 ACL 連線），
    而不是被動偵測。使用者帶著手機離開後，對不存在的裝置每一次嘗試探測都是一次硬體風險。
    在 Pi Zero 2W 的 BCM43438 晶片上，懸掛的 pending 連線堆積會導致藍牙控制器停止回應
    HCI 指令（dmesg 出現 command 0x0406 tx timeout, Opcode 0x200b / 0x0c03 failed: -110），
    甚至連 HCI_Reset 都超時卡死，最終整顆晶片死鎖只能重開機。
    因此手機不在場時必須盡量少探，退避上限拉高至 1800 秒（30 分鐘），將曝險比之前再降 3 倍。
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
    2. 2026-08-05 實機事故對策：l2ping 失敗（returncode != 0 或逾時/例外）之後，
       best-effort 呼叫 `hcitool dc <mac>`（timeout 3 秒，任何失敗都忽略、不影響回傳值），
       主動關閉可能懸掛在 BCM43438 晶片中的 ACL 連線，消除連線堆積風險。
    3. 在場才進一步用 hcitool rssi 取信號強度；同樣容錯，取不到就回 None，
       不影響「在場」這個判定本身（RSSI 只是輔助門檻，見 decide()）。
    4. 2026-08-04 實機事故保險：同時只允許一個 probe 在跑。若上一輪 l2ping
       還卡在 kernel 或 BCM43438 晶片層沒收乾淨，拿不到 _PROBE_LOCK 就立刻
       放棄並回 (False, None)，絕不在控制器上再疊一層 pending 連線。
    """
    if not _PROBE_LOCK.acquire(blocking=False):
        return False, None

    try:
        ping_ok = False
        try:
            ping = runner(["l2ping", "-c1", "-t2", mac], capture_output=True,
                          text=True, timeout=PROBE_TIMEOUT_S)
            if ping.returncode == 0:
                ping_ok = True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            ping_ok = False

        if not ping_ok:
            # 2026-08-05 實機事故對策：l2ping 失敗後 best-effort 清理懸掛的 ACL 連線
            try:
                runner(["hcitool", "dc", mac], capture_output=True, text=True, timeout=3)
            except Exception:
                pass
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


def parse_ble_rssi(output: str) -> int | None:
    """解析 bluetoothctl 輸出的 RSSI 值（純函數，不做 I/O，不拋例外）。

    2026-08-06 實機驗證：BlueZ 被動 BLE 掃描輸出可能包含 ANSI 色碼與 Hex RSSI 格式，
    例如 `RSSI: 0xffffffc7 (-57)`，亦可能為簡化格式 `RSSI: -57`。
    多筆紀錄時（前面為廣播掃描、最後為 info <MAC> 結果）必須取最後一筆。
    """
    if not isinstance(output, str) or not output:
        return None
    try:
        clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
        matches = list(re.finditer(r"RSSI:\s*(?:0x[0-9a-fA-F]+\s*\((-?\d+)\)|(-?\d+))", clean))
        if not matches:
            return None
        last_m = matches[-1]
        val_str = last_m.group(1) or last_m.group(2)
        if val_str is None:
            return None
        return int(val_str)
    except Exception:
        return None


def probe_ble_once(mac: str, runner=subprocess.run) -> tuple[bool, int | None]:
    """探測一次 BLE 裝置的訊號強度（不建立 ACL 連線）。

    2026-08-05 實機事故教訓：l2ping 建立主動 ACL 連線時，對方不在場會導致懸掛請求
    堆積在 BCM43438 控制器中，最終驅動層 tx timeout 並死鎖硬體。
    2026-08-06 實機驗證：改採被動 BLE 掃描（bluetoothctl 配合 scan on + info <MAC>），
    由 BlueZ 利用配對時取得的 IRK 自動將手機輪替的隨機 MAC 解析回固定 MAC，
    完全不對手機建立任何連線即可取得 RSSI，根治晶片卡死風險。
    """
    if not isinstance(mac, str) or not _MAC_RE.match(mac):
        return False, None

    if not _PROBE_LOCK.acquire(blocking=False):
        return False, None

    try:
        pipeline = (
            f'(echo "menu scan"; echo "transport le"; echo "back"; '
            f'echo "scan on"; sleep 8; '
            f'echo "info {mac}"; sleep 1; '
            f'echo "scan off"; echo "quit") | bluetoothctl'
        )
        proc = runner(
            ["bash", "-c", pipeline],
            capture_output=True,
            text=True,
            timeout=BLE_PROBE_TIMEOUT_S,
        )
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        rssi = parse_ble_rssi(out)
        if rssi is not None:
            return True, rssi
        return False, None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, Exception):
        return False, None
    finally:
        _PROBE_LOCK.release()


def adapter_healthy(runner=subprocess.run) -> bool:
    """跑 `hciconfig hci0`，讀得到就是活著。逾時、指令不存在、rc != 0、
    或輸出含 "Can't init device" 都視為不健康。任何例外都回 False，不拋出。

    2026-08-05 實機事故：Pi Zero 2W 控制器卡死時，hciconfig hci0 會輸出
    "Can't init device ..." 或超時不回應。
    """
    try:
        proc = runner(["hciconfig", "hci0"], capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            return False
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        out = stdout + stderr
        if "Can't init device" in out:
            return False
        return True
    except Exception:
        return False


def try_recover_adapter(runner=subprocess.run) -> bool:
    """兩段式復原，回傳是否成功：
    1. sudo -n systemctl restart bluetooth；等 3 秒後重新檢查 adapter_healthy()
    2. 還是不健康 → sudo -n hciconfig hci0 reset；再等 3 秒重新檢查
    兩段都失敗回 False。任何例外都吞掉回 False，不得拋出。

    2026-08-05 實機事故經驗：當 BCM43438 控制器 tx timeout 時，嘗試透過重啟服務
    或重置 hci0 復原硬體鎖定狀態。
    """
    try:
        try:
            runner(["sudo", "-n", "systemctl", "restart", "bluetooth"],
                   capture_output=True, text=True, timeout=10)
        except Exception:
            pass
        _time.sleep(3)
        if adapter_healthy(runner=runner):
            return True

        try:
            runner(["sudo", "-n", "hciconfig", "hci0", "reset"],
                   capture_output=True, text=True, timeout=10)
        except Exception:
            pass
        _time.sleep(3)
        if adapter_healthy(runner=runner):
            return True

        return False
    except Exception:
        return False


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
       晶片健康檢查與退避復原機制仍全數保留。
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
                            sleep_time = next_sleep(effective_interval, fail_streak)
                        else:
                            prev = state.snapshot().presence
                            state.set_presence(replace(prev, present=False, rssi=None, enabled=True))
                            sleep_time = UNHEALTHY_RECHECK_S
                    else:
                        present_probe, rssi = probe_fn(mac_now)
                        if present_probe:
                            fail_streak = 0
                        else:
                            fail_streak += 1
                            if fail_streak == RECOVERY_AFTER_FAILS:
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
                            sleep_time = UNHEALTHY_RECHECK_S
                        else:
                            new = decide(present_probe, rssi, threshold, prev, now, grace)
                            state.set_presence(replace(new, enabled=True))
                            sleep_time = next_sleep(effective_interval, fail_streak)
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
