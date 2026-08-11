from __future__ import annotations

import re
import subprocess
import threading
import time as _time

_RSSI_RE = re.compile(r"-?\d+")
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

PROBE_TIMEOUT_S = 5        # 既有 subprocess timeout，抽成常量（原本硬寫在 probe_once）
BLE_SCAN_SECONDS = 8          # 單次掃描視窗
BLE_PROBE_TIMEOUT_S = 20      # 整個 bluetoothctl 子行程的上限
_PROBE_LOCK = threading.Lock()


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


def parse_dbus_rssi(output: str) -> int | None:
    """解析 D-Bus Get RSSI 屬性指令的輸出（純函數，不做 I/O，不拋例外）。

    2026-08-06 實機假陽性 Bug 修正對策：
    前版解析 bluetoothctl 全區輸出會被周圍其他裝置的 [CHG] Device ... RSSI 訊號干擾，
    對不存在的 MAC 連續探測 10 次皆誤判為 (True, -72)。
    改用 D-Bus 針對指定裝置讀取 RSSI 屬性：
    - 在場時輸出包含 "variant       int16 -55"
    - 不在場或無 RSSI 時輸出包含 "Error org.freedesktop.DBus.Error.InvalidArgs: No such property 'RSSI'"
    """
    if not isinstance(output, str) or not output:
        return None
    if "Error" in output or "No such property" in output:
        return None
    try:
        m = re.search(r"int16\s+(-?\d+)", output)
        if not m:
            return None
        return int(m.group(1))
    except Exception:
        return None


def mac_to_dbus_path(mac: str) -> str | None:
    """將 MAC 位址轉換為 BlueZ D-Bus 裝置物件路徑（純函數，不做 I/O，不拋例外）。

    例如 "c4:c1:7d:63:07:88" -> "/org/bluez/hci0/dev_C4_C1_7D_63_07_88"。
    若 MAC 不合法則傳回 None。
    """
    if not isinstance(mac, str) or not _MAC_RE.match(mac):
        return None
    formatted = mac.replace(":", "_").upper()
    return f"/org/bluez/hci0/dev_{formatted}"


def probe_ble_once(mac: str, runner=subprocess.run) -> tuple[bool, int | None]:
    """探測一次 BLE 裝置的訊號強度（不建立 ACL 連線）。

    2026-08-05 實機事故教訓：l2ping 建立主動 ACL 連線時，對方不在場會導致懸掛請求
    堆積在 BCM43438 控制器中，最終驅動層 tx timeout 並死鎖硬體。
    2026-08-06 實機假陽性 Bug 修正：原先 parse_ble_rssi() 解析掃描期間 bluetoothctl
    輸出的整段紀錄並取最後一筆 RSSI，但掃描期間周圍其他裝置的 RSSI 變更事件
    （例如 [CHG] Device XX:XX:XX:XX:XX:XX RSSI: -70）會持續刷進輸出，
    實測對根本不存在的 MAC (AA:BB:CC:DD:EE:FF) 連續探測 10 次，每一次都回報 (True, -72)
    這種假陽性，導致 presence 永遠回報在場、presence_hide_accounts 的私人行事曆遮蔽功能失效。
    正確做法：背景跑被動掃描（掃描命令末端帶 scan off; quit 確保自動收尾），
    掃描中途利用 dbus-send 針對特定目標裝置路徑直接讀取 RSSI 屬性。
    掃描在背景跑並自己 scan off; quit 收尾，即使 dbus 讀取失敗也不會留下殘留的 discovery session。
    """
    dev_path = mac_to_dbus_path(mac)
    if dev_path is None:
        return False, None

    if not _PROBE_LOCK.acquire(blocking=False):
        return False, None

    try:
        pipeline = (
            '(echo "menu scan"; echo "transport le"; echo "back"; '
            'echo "scan on"; sleep 8; echo "scan off"; echo "quit") | bluetoothctl >/dev/null 2>&1 &\n'
            'sleep 7\n'
            f'dbus-send --system --print-reply --dest=org.bluez {dev_path} '
            'org.freedesktop.DBus.Properties.Get string:org.bluez.Device1 string:RSSI\n'
            'wait'
        )
        proc = runner(
            ["bash", "-c", pipeline],
            capture_output=True,
            text=True,
            timeout=BLE_PROBE_TIMEOUT_S,
        )
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        out = stdout + stderr
        rssi = parse_dbus_rssi(out)
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
