"""nmcli 包裝：Wi-Fi 掃描/連線/狀態，給設定頁的 Wi-Fi 畫面用。

設計約束：
- 執行面全部 subprocess＋timeout，任何失敗（沒裝 nmcli、逾時、rc≠0）都回
  安全預設值（空清單/False），絕不讓例外穿進 render loop——Mac dev 模式沒有
  nmcli，畫面要能顯示「不支援」而不是炸掉。
- 解析函式是純函式（吃 nmcli -t 的輸出字串），單元測試餵假輸出即可。
- Pi 上實測 kevin 使用者屬 netdev 群組，nmcli 掃描/連線不需要 sudo。
- 密碼只以 argv 形式傳給 nmcli（不落地、不進 log；本機單一使用者裝置，
  ps 短暫可見視為可接受）。錯誤訊息一律截短且不含密碼。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

_TIMEOUT_SCAN = 20
_TIMEOUT_CONNECT = 45
WLAN_DEV = "wlan0"          # Pi Zero 2 W 內建無線介面


@dataclass(frozen=True)
class WifiNet:
    ssid: str
    signal: int             # 0-100
    secured: bool
    active: bool
    known: bool             # NetworkManager 已存過的連線（不用再輸入密碼）


def _run(args: list, timeout: int) -> "tuple[int, str]":
    """跑 nmcli；任何層級的失敗都收斂成 (rc, 訊息)，不往外丟例外。"""
    try:
        r = subprocess.run(["nmcli"] + args, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, "nmcli 不存在（非 NetworkManager 環境）"
    except subprocess.TimeoutExpired:
        return -1, "nmcli 逾時"
    except OSError as e:
        return -1, f"nmcli 執行失敗：{e}"


def _split_t(line: str) -> list:
    """拆 nmcli -t 的一行：欄位以「未跳脫的冒號」分隔，SSID 內的冒號會被
    nmcli 寫成 \\:（反斜線跳脫）。"""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def parse_known(text: str) -> set:
    """`nmcli -t -f NAME,TYPE connection show` → 已儲存的 Wi-Fi 連線名集合。"""
    known = set()
    for line in text.splitlines():
        f = _split_t(line.strip())
        if len(f) >= 2 and f[1] == "802-11-wireless" and f[0]:
            known.add(f[0])
    return known


def parse_wifi_list(text: str, known: set) -> list:
    """`nmcli -t -f ACTIVE,SSID,SIGNAL,SECURITY dev wifi list` → [WifiNet]。
    同名 SSID（多 AP）只留訊號最強者；空 SSID（隱藏網路）跳過；ACTIVE=yes
    優先保留（active 旗標不能被較強的非活動 AP 蓋掉）。"""
    best: dict = {}
    for line in text.splitlines():
        f = _split_t(line.strip())
        if len(f) < 4 or not f[1]:
            continue
        try:
            signal = int(f[2])
        except ValueError:
            continue
        net = WifiNet(
            ssid=f[1], signal=max(0, min(100, signal)),
            secured=f[3].strip() not in ("", "--"),
            active=f[0] == "yes", known=f[1] in known)
        old = best.get(net.ssid)
        if old is None or net.active or (not old.active and net.signal > old.signal):
            if old is not None and old.active and not net.active:
                continue
            best[net.ssid] = net
    return sorted(best.values(), key=lambda n: (not n.active, -n.signal))


def known_ssids() -> set:
    rc, out = _run(["-t", "-f", "NAME,TYPE", "connection", "show"], _TIMEOUT_SCAN)
    return parse_known(out) if rc == 0 else set()


def scan() -> list:
    """觸發重掃＋回傳目前看得到的網路（依訊號排序、活動中優先）。失敗回空清單。"""
    _run(["dev", "wifi", "rescan"], _TIMEOUT_SCAN)      # rc 忽略：太頻繁會被拒，無妨
    rc, out = _run(["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi",
                    "list"], _TIMEOUT_SCAN)
    if rc != 0:
        return []
    return parse_wifi_list(out, known_ssids())


def active_info() -> "tuple[str, str] | None":
    """目前連線的 (SSID, IPv4)；未連線回 None。"""
    rc, out = _run(["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi",
                    "list"], _TIMEOUT_SCAN)
    if rc != 0:
        return None
    ssid = None
    for line in out.splitlines():
        f = _split_t(line.strip())
        if len(f) >= 2 and f[0] == "yes" and f[1]:
            ssid = f[1]
            break
    if ssid is None:
        return None
    rc, out = _run(["-t", "-f", "IP4.ADDRESS", "dev", "show", WLAN_DEV],
                   _TIMEOUT_SCAN)
    ip = ""
    if rc == 0:
        for line in out.splitlines():
            f = _split_t(line.strip())
            if len(f) >= 2 and f[1]:
                ip = f[1].split("/")[0]
                break
    return (ssid, ip)


def connect(ssid: str, password: "str | None" = None) -> "tuple[bool, str]":
    """連線。有給密碼＝視為（重）設定這個網路：先刪同名舊 profile 再連，
    避免上次打錯密碼留下的殘缺 profile 讓 nmcli 回「connection exists」。
    沒給密碼＝開放網路或已儲存的網路，直接用既有 profile 連。
    回 (成功?, 給人看的短訊息——絕不含密碼)。"""
    if password:
        _run(["connection", "delete", "id", ssid], 10)   # rc 忽略：本來就可能不存在
        rc, out = _run(["dev", "wifi", "connect", ssid, "password", password],
                       _TIMEOUT_CONNECT)
    else:
        rc, out = _run(["dev", "wifi", "connect", ssid], _TIMEOUT_CONNECT)
    msg = " ".join(out.split())[:140]      # 壓成單行截短；nmcli 輸出不含密碼原文
    return rc == 0, msg
