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

import hashlib
import subprocess
from dataclasses import dataclass

_TIMEOUT_SCAN = 20
_TIMEOUT_CONNECT = 60       # 弱訊號 AP 的關聯+DHCP 可能拖很久，45 秒實測會誤殺
WLAN_DEV = "wlan0"          # Pi Zero 2 W 內建無線介面


@dataclass(frozen=True)
class WifiNet:
    ssid: str
    signal: int             # 0-100
    secured: bool
    active: bool
    known: bool             # NetworkManager 已存過的連線（不用再輸入密碼）
    security: str = ""      # nmcli SECURITY 原文（如 "WPA2"/"WPA3"），連線時選 key-mgmt 用
    profile_id: str = ""    # NetworkManager connection profile ID (NAME)


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


def parse_known(text: str) -> dict[str, str]:
    """`nmcli -t -f NAME,TYPE,802-11-wireless.ssid connection show` → {SSID: profile_id}。"""
    known = {}
    for line in text.splitlines():
        f = _split_t(line.strip())
        if len(f) >= 2 and f[1] == "802-11-wireless" and f[0]:
            profile_id = f[0]
            ssid = f[2] if (len(f) >= 3 and f[2] and f[2] != "--") else f[0]
            known[ssid] = profile_id
    return known


def parse_wifi_list(text: str, known: dict | set) -> list:
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
        ssid = f[1]
        is_known = ssid in known
        if isinstance(known, dict):
            profile_id = known.get(ssid, "")
        else:
            profile_id = ssid if is_known else ""
        net = WifiNet(
            ssid=ssid, signal=max(0, min(100, signal)),
            secured=f[3].strip() not in ("", "--"),
            active=f[0] == "yes", known=is_known,
            security=f[3].strip(),
            profile_id=profile_id)
        old = best.get(net.ssid)
        if old is None or net.active or (not old.active and net.signal > old.signal):
            if old is not None and old.active and not net.active:
                continue
            best[net.ssid] = net
    return sorted(best.values(), key=lambda n: (not n.active, -n.signal))


def known_ssids() -> dict[str, str]:
    """回傳 {實際 SSID: NetworkManager profile ID}。

    `nmcli connection show` 的清單模式只允許 NAME/TYPE 等欄位，不能直接取
    ``802-11-wireless.ssid``。先取得 Wi-Fi profile ID，再個別讀取其實際 SSID，
    才能處理 profile 名稱與 AP 廣播名稱不同的情境。
    """
    rc, out = _run(["-t", "-f", "NAME,TYPE", "connection", "show"], _TIMEOUT_SCAN)
    if rc != 0:
        return {}

    profiles = parse_known(out)
    known: dict[str, str] = {}
    for profile_id in set(profiles.values()):
        rc, ssid_out = _run(
            ["-g", "802-11-wireless.ssid", "connection", "show", "id", profile_id],
            _TIMEOUT_SCAN,
        )
        ssid = ssid_out.strip()
        if rc == 0 and ssid and ssid != "--":
            known[ssid] = profile_id
    return known


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


def connect(ssid: str, password: "str | None" = None,
            security: str = "", profile_id: str = "") -> "tuple[bool, str]":
    """連線。回 (成功?, 給人看的短訊息——絕不含密碼)。

    有給密碼＝（重）設定這個網路：先建立暫時 profile（con-name 不等於 target profile id）
    並帶起；成功後才刪 target profile id (profile_id 無則 SSID) 並將暫時 profile 改名為 target profile id，
    維持 known_ssids 邏輯。若失敗僅刪除暫時 profile，保留既有 profile 作
    回退。key-mgmt 由掃描結果的 SECURITY 欄自選：WPA3-only → sae，
    其餘 → wpa-psk（WPA2/WPA3 過渡模式用 wpa-psk 可連）。

    沒給密碼＝開放網路或已儲存的網路：傳 profile_id 則優先 `connection up id <profile_id>`
    且失敗不得 fallback；未傳 profile_id 則先 `connection up id <ssid>`，沒有 profile 再退回 `dev wifi connect`。
    """
    if password:
        target_id = profile_id if profile_id else ssid
        temp_id = f"temp-{hashlib.sha256(ssid.encode()).hexdigest()[:8]}"
        if temp_id == target_id:
            temp_id = f"temp2-{hashlib.sha256(ssid.encode()).hexdigest()[:8]}"
        _run(["connection", "delete", "id", temp_id], 10)   # rc 忽略：本來就可能不存在
        key_mgmt = "sae" if ("WPA3" in security and "WPA2" not in security) \
            else "wpa-psk"
        rc, out = _run(["connection", "add", "type", "wifi", "ifname", WLAN_DEV,
                        "con-name", temp_id, "ssid", ssid,
                        "wifi-sec.key-mgmt", key_mgmt, "wifi-sec.psk", password,
                        "connection.autoconnect", "no"], 15)
        if rc == 0:
            rc, out = _run(["connection", "up", "id", temp_id], _TIMEOUT_CONNECT)
        if rc == 0:
            _run(["connection", "delete", "id", target_id], 10)
            _run(["connection", "modify", "id", temp_id, "connection.id", target_id,
                  "connection.autoconnect", "yes"], 10)
        else:
            # 失敗僅清理暫時 profile，保留既有 target_id profile 作回退。
            _run(["connection", "delete", "id", temp_id], 10)
    else:
        if profile_id:
            rc, out = _run(["connection", "up", "id", profile_id], _TIMEOUT_CONNECT)
        else:
            rc, out = _run(["connection", "up", "id", ssid], _TIMEOUT_CONNECT)
            if rc != 0:
                rc, out = _run(["dev", "wifi", "connect", ssid], _TIMEOUT_CONNECT)
    msg = " ".join(out.split())[:140]      # 壓成單行截短；nmcli 輸出不含密碼原文
    return rc == 0, msg
