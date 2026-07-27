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
    assert wifi.parse_known(text) == {"Home5G", "Office"}


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


def test_connect_with_password_deletes_stale_profile_first(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="successfully activated", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("Office", "s3cret!pw")
    assert ok
    assert calls[0][:4] == ["nmcli", "connection", "delete", "id"]
    assert calls[1][:4] == ["nmcli", "dev", "wifi", "connect"]
    assert "password" in calls[1]
    assert "s3cret!pw" not in msg, "訊息不得含密碼"


def test_connect_without_password_uses_saved_profile(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, _ = wifi.connect("Home5G")
    assert ok
    assert len(calls) == 1 and "password" not in calls[0]


def test_connect_failure_returns_false_with_short_message(monkeypatch):
    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 4, stdout="", stderr="Error: Connection activation failed: " + "x" * 500)

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    ok, msg = wifi.connect("Office", "pw")
    assert ok is False
    assert len(msg) <= 140
    # 失敗後必須把 nmcli 剛建立的壞 profile 清掉——留著會讓這個網路變成
    # 「已儲存」、之後點了直接用壞密碼連、密碼鍵盤永遠不再出現。
    deletes = [c for c in calls if c[:4] == ["nmcli", "connection", "delete", "id"]]
    assert len(deletes) == 2, "連線失敗後應再刪一次壞 profile（前置刪＋失敗清理）"


def test_scan_returns_empty_when_nmcli_missing(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        raise FileNotFoundError("nmcli")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    assert wifi.scan() == []
    assert wifi.active_info() is None
    ok, msg = wifi.connect("X", "y")
    assert ok is False and "nmcli" in msg
