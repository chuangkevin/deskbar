"""bluetoothctl 包裝：掃描/配對/解除配對，給設定頁「藍牙配對」畫面用。

配對到的裝置直接設為在場感應目標（settings.presence_mac）——使用者在螢幕上
點裝置完成配對，不必手抄 MAC；配對過的裝置對 l2ping 的回應也遠比未配對
穩定（未配對的手機常不回 L2CAP echo，是「開了藍牙沒反應」的主因之一）。

實作約束（比照 deskbar.wifi）：
- 全部 subprocess＋timeout，任何失敗收斂成安全值，不讓例外穿進 render loop。
- 解析函式是純函式（吃 bluetoothctl 輸出字串），單元測試餵假輸出。
- 配對流程使用有時序延遲的 shell pipeline：
  2026-08-06 實機重現抓到三個問題：
  1. 代理註冊失敗：bluetoothctl 在 Waiting to connect to bluetoothd 時即處理 agent 指令，
     導致 Failed to register agent object 與 No agent is registered。指令間加延遲可確保註冊成功。
  2. 未回應 SSP 數字比對：手機端要求 Confirm passkey，舊腳本未自動送 yes。
  3. 異步配對過早結束：pair 為異步指令，若未等待即 quit 會中止配對。
  是以實測出來的延遲值透過 Bash pipeline 依序餵給 bluetoothctl，並等待手機端確認。
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

_TIMEOUT_CMD = 15
_TIMEOUT_PAIR = 90
SCAN_SECONDS = 8

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


@dataclass(frozen=True)
class BtDevice:
    mac: str
    name: str
    paired: bool


def _run(args: list, timeout: int, input_text: "str | None" = None) -> "tuple[int, str]":
    try:
        r = subprocess.run(["bluetoothctl"] + args, capture_output=True, text=True,
                           timeout=timeout, input=input_text)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, "bluetoothctl 不存在"
    except subprocess.TimeoutExpired:
        return -1, "bluetoothctl 逾時"
    except OSError as e:
        return -1, f"bluetoothctl 執行失敗：{e}"


def parse_devices(text: str, paired_macs: set) -> list:
    """`bluetoothctl devices` 輸出（每行 `Device <MAC> <名稱>`）→ [BtDevice]。
    同 MAC 取最後出現的名稱；名稱剛好等於 MAC（藍牙位址當名稱＝未解析出
    真名的殘影）視為無名。"""
    seen: dict = {}
    for line in text.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) < 2 or parts[0] != "Device":
            continue
        mac = parts[1].upper()
        if mac.count(":") != 5:
            continue
        name = parts[2].strip() if len(parts) > 2 else ""
        if name.replace("-", ":").upper() == mac:
            name = ""
        seen[mac] = BtDevice(mac=mac, name=name, paired=mac in paired_macs)
    devs = list(seen.values())
    devs.sort(key=lambda d: (not d.paired, d.name == "", d.name or d.mac))
    return devs


def parse_paired(text: str) -> set:
    macs = set()
    for line in text.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and parts[1].count(":") == 5:
            macs.add(parts[1].upper())
    return macs


def paired_macs() -> set:
    rc, out = _run(["devices", "Paired"], _TIMEOUT_CMD)
    if rc != 0 or "Invalid argument" in out:
        rc, out = _run(["paired-devices"], _TIMEOUT_CMD)   # 舊版 bluez 語法
        if rc != 0:
            return set()
    return parse_paired(out)


def scan(seconds: int = SCAN_SECONDS) -> list:
    """開電源→阻塞掃描 N 秒→列出所見裝置（含已配對）。失敗回空清單。"""
    _run([], 10, input_text="power on\nquit\n")            # rc 忽略：可能已開
    _run(["--timeout", str(seconds), "scan", "on"], seconds + 8)
    rc, out = _run(["devices"], _TIMEOUT_CMD)
    if rc != 0:
        return []
    return parse_devices(out, paired_macs())


def parse_pair_result(output: str) -> "tuple[bool, str]":
    """判讀 bluetoothctl 配對輸出，回 (成功?, 給人看的短訊息)。"""
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output or "")

    if "Pairing successful" in text or "Paired: yes" in text:
        return True, "配對成功"
    if "AlreadyExists" in text:
        return True, "已配對"
    if "AuthenticationFailed" in text:
        return False, "手機端未確認配對（請在手機上按接受後重試）"
    if "AuthenticationTimeout" in text:
        return False, "配對逾時（手機端沒有回應）"
    if "AuthenticationCanceled" in text:
        return False, "配對被取消"
    if "Failed to register agent" in text or "No agent is registered" in text:
        return False, "藍牙代理註冊失敗"
    if re.search(r"Device .* not available", text) or "org.bluez.Error.DoesNotExist" in text:
        return False, "找不到裝置（請先讓手機進入可被搜尋狀態）"

    msg = " ".join(text.split())[-140:]
    return False, msg or "配對失敗"


def pair(mac: str) -> "tuple[bool, str]":
    """配對＋信任。手機端會跳確認框，必須兩邊確認。
    過濾無效 MAC 後以時序 shell pipeline 餵給 bluetoothctl 執行。
    """
    if not _MAC_RE.match(mac):
        return False, "MAC 格式不正確"

    pipeline = (
        f'(echo "power on"; sleep 2; '
        f'echo "agent NoInputNoOutput"; sleep 2; '
        f'echo "default-agent"; sleep 2; '
        f'echo "pair {mac}"; sleep 6; '
        f'echo "yes"; sleep 30; '
        f'echo "trust {mac}"; sleep 3; '
        f'echo "quit") | bluetoothctl'
    )
    try:
        r = subprocess.run(
            ["bash", "-c", pipeline],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_PAIR,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return parse_pair_result(out)
    except FileNotFoundError:
        return False, "bluetoothctl 不存在"
    except subprocess.TimeoutExpired:
        return False, "配對逾時"
    except OSError as e:
        return False, f"bluetoothctl 執行失敗：{e}"



def unpair(mac: str) -> "tuple[bool, str]":
    rc, out = _run(["remove", mac], _TIMEOUT_CMD)
    ok = rc == 0 or "has been removed" in out or "not available" in out.lower()
    return ok, "已解除配對" if ok else " ".join(out.split())[-120:]
