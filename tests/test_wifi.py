"""deskbar.wifi（nmcli 包裝）：-t 輸出解析純函式、連線參數組裝、
失敗收斂不丟例外、錯誤訊息不含密碼。"""
from __future__ import annotations

import subprocess

from deskbar import wifi


def test_split_t_handles_escaped_colons_in_ssid():
    assert wifi._split_t(r"yes:My\:SSID:72:WPA2") == ["yes", "My:SSID", "72", "WPA2"]
    assert wifi._split_t("a:b:c") == ["a", "b", "c"]
    assert wifi._split_t("") == [""]


def test_parse_known_only_wifi_connections():
    text = "Home5G:802-11-wireless\nWired 1:802-3-ethernet\nlo:loopback\nOffice:802-11-wireless"
    assert wifi.parse_known(text) == {"Home5G": "Home5G", "Office": "Office"}


def test_parse_known_actual_ssid_mapping():
    text = "interagent:802-11-wireless:InterAgent - Enterprise\nHome5G:802-11-wireless:\nOffice:802-11-wireless:--"
    known = wifi.parse_known(text)
    assert known == {
        "InterAgent - Enterprise": "interagent",
        "Home5G": "Home5G",
        "Office": "Office",
    }


def test_parse_wifi_list_known_and_profile_id():
    text = "no:InterAgent - Enterprise:80:WPA2\nno:OtherSSID:60:WPA2"
    mapping = {"InterAgent - Enterprise": "interagent"}
    nets = wifi.parse_wifi_list(text, known=mapping)
    assert nets[0].ssid == "InterAgent - Enterprise"
    assert nets[0].known is True
    assert nets[0].profile_id == "interagent"
    assert nets[1].known is False
    assert nets[1].profile_id == ""

    # 維持 set 型 known 的向後相容
    nets_set = wifi.parse_wifi_list(text, known={"InterAgent - Enterprise"})
    assert nets_set[0].known is True
    assert nets_set[0].profile_id == "InterAgent - Enterprise"


def test_parse_wifi_list_dedupes_and_sorts():
    text = "\n".join([
        "no:Home5G:55:WPA2",
        "no:Home5G:83:WPA2",          # 同名較強 AP → 應保留 83
        "yes:Hotspot:30:WPA2",        # 活動中 → 排最前，且不被強訊號蓋掉
        "no::99:WPA2",                # 隱藏 SSID → 跳過
        "no:OpenCafe:64:",            # 無加密
        "no:Hotspot:90:WPA2",         # 活動中同名的另一顆 AP → 不得蓋掉 active 旗標
    ])
    nets = wifi.parse_wifi_list(text, known={"Home5G"})
    assert [n.ssid for n in nets] == ["Hotspot", "Home5G", "OpenCafe"]
    hotspot, home, cafe = nets
    assert hotspot.active and hotspot.signal == 30
    assert home.signal == 83 and home.known and home.secured
    assert cafe.secured is False and cafe.known is False


def test_connect_with_password_builds_explicit_profile(monkeypatch):
    """有密碼＝先建暫時 profile（con-name ≠ SSID）並 up → 成功後才刪舊 id=SSID 並改名。
    不走 dev wifi connect——那條路依賴掃描快取推斷加密，AP 不在快取就報
    key-mgmt property is missing（實機 Kevin_2.4 踩到）。"""
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="successfully activated", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("Office", "s3cret!pw", security="WPA2")
    assert ok
    # 建立前清理這個暫時 profile
    assert calls[0][:4] == ["nmcli", "connection", "delete", "id"]
    temp_id = calls[0][4]
    assert temp_id != "Office" and temp_id.startswith("temp-")

    # 建立暫時 profile (con-name 為 temp_id)
    assert calls[1][:3] == ["nmcli", "connection", "add"]
    con_idx = calls[1].index("con-name")
    assert calls[1][con_idx + 1] == temp_id
    ssid_idx = calls[1].index("ssid")
    assert calls[1][ssid_idx + 1] == "Office"
    assert "wpa-psk" in calls[1] and "wifi-sec.psk" in calls[1]
    auto_idx = calls[1].index("connection.autoconnect")
    assert calls[1][auto_idx + 1] == "no"

    # 帶起暫時 profile
    assert calls[2] == ["nmcli", "connection", "up", "id", temp_id]

    # 啟動成功後才刪除舊 id=SSID profile，並將暫時 profile 改名為 SSID
    assert calls[3] == ["nmcli", "connection", "delete", "id", "Office"]
    assert calls[4] == ["nmcli", "connection", "modify", "id", temp_id,
                        "connection.id", "Office", "connection.autoconnect", "yes"]

    assert "s3cret!pw" not in msg, "訊息不得含密碼"


def test_connect_key_mgmt_follows_scanned_security(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    wifi.connect("Pure3", "pw", security="WPA3")
    assert "sae" in calls[1], "WPA3-only 要用 sae"
    calls.clear()
    wifi.connect("Mixed", "pw", security="WPA2 WPA3")
    assert "wpa-psk" in calls[1], "WPA2/WPA3 過渡模式用 wpa-psk"


def test_connect_without_password_prefers_saved_profile_then_falls_back(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        rc = 10 if args[:3] == ["nmcli", "connection", "up"] else 0
        return subprocess.CompletedProcess(args, rc, stdout="ok", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, _ = wifi.connect("OpenCafe")
    assert ok
    assert calls[0][:3] == ["nmcli", "connection", "up"], "先試既有 profile"
    assert calls[1][:4] == ["nmcli", "dev", "wifi", "connect"], "沒 profile 退回開放網路路徑"
    assert all("password" not in c for c in calls)


def test_connect_without_password_uses_profile_id_and_no_fallback(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="error")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("InterAgent - Enterprise", profile_id="interagent")
    assert ok is False
    assert len(calls) == 1, "傳 profile_id 失敗時不得再走 dev wifi connect fallback"
    assert calls[0] == ["nmcli", "connection", "up", "id", "interagent"]


def test_connect_password_success_replaces_non_matching_existing_profile(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="activated", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, _ = wifi.connect("InterAgent - Enterprise", "secret123", security="WPA2", profile_id="interagent")
    assert ok is True
    # 啟動成功後刪除舊 target profile id "interagent"
    assert ["nmcli", "connection", "delete", "id", "interagent"] in calls
    modify_call = next(c for c in calls if c[:3] == ["nmcli", "connection", "modify"])
    temp_id = calls[0][4]
    assert modify_call == ["nmcli", "connection", "modify", "id", temp_id,
                           "connection.id", "interagent", "connection.autoconnect", "yes"]


def test_connect_password_failure_preserves_non_matching_existing_profile(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        rc = 4 if args[:3] == ["nmcli", "connection", "up"] and len(args) >= 5 and args[4].startswith("temp-") else 0
        return subprocess.CompletedProcess(args, rc, stdout="", stderr="Error: Connection activation failed")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, _ = wifi.connect("InterAgent - Enterprise", "wrongpass", security="WPA2", profile_id="interagent")
    assert ok is False
    deleted_ids = [c[4] for c in calls if c[:4] == ["nmcli", "connection", "delete", "id"]]
    assert "interagent" not in deleted_ids, "失敗時保留既有 existing profile_id"
    assert "InterAgent - Enterprise" not in deleted_ids


def test_connect_failure_returns_false_with_short_message(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 4, stdout="", stderr="Error: Connection activation failed: " + "x" * 500)

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("Office", "pw", security="WPA2")
    assert ok is False
    assert len(msg) <= 140
    # 失敗後必須把 nmcli 剛建立的壞 profile 清掉——留著會讓這個網路變成
    # 「已儲存」、之後點了直接用壞密碼連、密碼鍵盤永遠不再出現。
    deletes = [c for c in calls if c[:4] == ["nmcli", "connection", "delete", "id"]]
    assert len(deletes) == 2, "連線失敗後應再刪一次壞 profile（前置刪＋失敗清理）"


def test_connect_failure_preserves_existing_ssid_profile(monkeypatch):
    """temp connection up 失敗時，絕不 delete id=SSID，僅清理 temp profile，回傳錯誤不含密碼。"""
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        rc = 4 if args[:3] == ["nmcli", "connection", "up"] else 0
        return subprocess.CompletedProcess(
            args, rc, stdout="", stderr="Error: Connection activation failed: secrets-failed")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("Office", "s3cret!pw", security="WPA2")
    assert ok is False
    assert "s3cret!pw" not in msg, "錯誤訊息不得含密碼"

    # 驗證從未刪除 id="Office" (既有 SSID profile)
    deleted_ids = [c[4] for c in calls if c[:4] == ["nmcli", "connection", "delete", "id"]]
    assert "Office" not in deleted_ids, "連線失敗時不得刪除既有 id=SSID profile"

    # 驗證僅清理暫時 profile
    assert len(deleted_ids) == 2, "應有 2 次刪除暫時 profile 操作（前置刪＋失敗清理）"
    assert deleted_ids[0] == deleted_ids[1]
    assert deleted_ids[0] != "Office" and deleted_ids[0].startswith("temp-")


def test_scan_returns_empty_when_nmcli_missing(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        raise FileNotFoundError("nmcli")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    assert wifi.scan() == []
    assert wifi.active_info() is None
    ok, msg = wifi.connect("X", "y")
    assert ok is False and "nmcli" in msg
