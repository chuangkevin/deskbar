"""bt.pair 與 parse_pair_result 的單元測試。

驗證藍牙配對輸出判讀邏輯、時序 shell pipeline 組裝、MAC 格式過濾，
以及各種例外（逾時、檔案不存在）的平滑收斂。
"""
from __future__ import annotations

import subprocess
from deskbar import bt
from deskbar.bt import parse_pair_result, pair


# ---------------------------------------------------------------- parse_pair_result 純函式測試

def test_parse_pair_result_success_pairing_successful():
    text = "[CHG] Device C4:C1:7D:63:07:88 Connected: yes\nPairing successful"
    ok, msg = parse_pair_result(text)
    assert ok is True
    assert msg == "配對成功"


def test_parse_pair_result_success_paired_yes():
    text = "Device C4:C1:7D:63:07:88 Paired: yes"
    ok, msg = parse_pair_result(text)
    assert ok is True
    assert msg == "配對成功"


def test_parse_pair_result_already_exists():
    text = "Failed to pair: org.bluez.Error.AlreadyExists"
    ok, msg = parse_pair_result(text)
    assert ok is True
    assert msg == "已配對"


def test_parse_pair_result_auth_failed():
    text = "Failed to pair: org.bluez.Error.AuthenticationFailed"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "手機端未確認配對（請在手機上按接受後重試）"


def test_parse_pair_result_auth_timeout():
    text = "Failed to pair: org.bluez.Error.AuthenticationTimeout"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "配對逾時（手機端沒有回應）"


def test_parse_pair_result_auth_canceled():
    text = "Failed to pair: org.bluez.Error.AuthenticationCanceled"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "配對被取消"


def test_parse_pair_result_agent_failed():
    text = "Failed to register agent object\nNo agent is registered"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "藍牙代理註冊失敗"


def test_parse_pair_result_device_not_available():
    text = "Device C4:C1:7D:63:07:88 not available"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "找不到裝置（請先讓手機進入可被搜尋狀態）"


def test_parse_pair_result_does_not_exist():
    text = "Failed to pair: org.bluez.Error.DoesNotExist"
    ok, msg = parse_pair_result(text)
    assert ok is False
    assert msg == "找不到裝置（請先讓手機進入可被搜尋狀態）"


def test_parse_pair_result_ansi_codes_stripped():
    text = "\x1b[0;94m[bluetoothctl]> \x1b[0mPairing successful"
    ok, msg = parse_pair_result(text)
    assert ok is True
    assert msg == "配對成功"


def test_parse_pair_result_empty_or_unknown_output():
    ok, msg = parse_pair_result("")
    assert ok is False
    assert isinstance(msg, str) and len(msg) > 0

    ok_unk, msg_unk = parse_pair_result("Some random unparsable text output")
    assert ok_unk is False
    assert isinstance(msg_unk, str) and len(msg_unk) > 0


# ---------------------------------------------------------------- pair() 整合與邊界測試

def test_pair_invalid_mac_does_not_call_subprocess(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    for invalid_mac in ["亂寫", "C4:C1:7D:63:07", "AA:BB:CC:DD:EE", "ZZ:BB:CC:DD:EE:FF"]:
        ok, msg = pair(invalid_mac)
        assert ok is False
        assert msg == "MAC 格式不正確"

    assert len(calls) == 0, "無效 MAC 不應呼叫 subprocess"


def test_pair_valid_mac_builds_correct_pipeline(monkeypatch):
    captured = {}

    def fake_run(args, capture_output=True, text=True, timeout=None):
        captured["cmd"] = args[2] if len(args) > 2 else ""
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args, 0, stdout="Pairing successful", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    mac = "C4:C1:7D:63:07:88"
    ok, msg = pair(mac)
    assert ok is True
    assert msg == "配對成功"
    pipeline = captured["cmd"]
    assert f"pair {mac}" in pipeline
    assert 'echo "yes"' in pipeline
    assert f"trust {mac}" in pipeline
    assert captured["timeout"] == 90


def test_pair_handles_timeout_expired(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="bash", timeout=90)

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = pair("C4:C1:7D:63:07:88")
    assert ok is False
    assert "逾時" in msg


def test_pair_handles_file_not_found(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("bluetoothctl")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, msg = pair("C4:C1:7D:63:07:88")
    assert ok is False
    assert "bluetoothctl 不存在" in msg
