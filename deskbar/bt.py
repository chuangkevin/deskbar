"""bluetoothctl 包裝：掃描/配對/解除配對，給設定頁「藍牙配對」畫面用。

配對到的裝置直接設為在場感應目標（settings.presence_mac）——使用者在螢幕上
點裝置完成配對，不必手抄 MAC；配對過的裝置對 l2ping 的回應也遠比未配對
穩定（未配對的手機常不回 L2CAP echo，是「開了藍牙沒反應」的主因之一）。

實作約束（比照 deskbar.wifi）：
- 全部 subprocess＋timeout，任何失敗收斂成安全值，不讓例外穿進 render loop。
- 解析函式是純函式（吃 bluetoothctl 輸出字串），單元測試餵假輸出。
- 配對用 stdin 腳本＋NoInputNoOutput agent（Just-Works）：Pi 端免輸入，
  手機端會跳「配對要求」對話框，使用者按確認即完成；成功後順手 trust，
  讓裝置重開機後仍可直接互連。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

_TIMEOUT_CMD = 15
_TIMEOUT_PAIR = 40
SCAN_SECONDS = 8


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


def pair(mac: str) -> "tuple[bool, str]":
    """配對＋信任。手機端會跳確認框，使用者按下確認才會成功；已配對過
    視為成功（冪等）。"""
    script = ("power on\nagent NoInputNoOutput\ndefault-agent\n"
              f"pair {mac}\ntrust {mac}\nquit\n")
    rc, out = _run([], _TIMEOUT_PAIR, input_text=script)
    ok = ("Pairing successful" in out) or ("AlreadyExists" in out)
    if ok:
        return True, "配對成功"
    msg = " ".join(out.split())[-140:]
    return False, msg or "配對失敗"


def unpair(mac: str) -> "tuple[bool, str]":
    rc, out = _run(["remove", mac], _TIMEOUT_CMD)
    ok = rc == 0 or "has been removed" in out or "not available" in out.lower()
    return ok, "已解除配對" if ok else " ".join(out.split())[-120:]
