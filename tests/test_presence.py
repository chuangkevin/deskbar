import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from deskbar import presence
from deskbar.config import Settings
from deskbar.presence import PresenceState
from deskbar.store import AppState

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)
NEVER = PresenceState(present=False, rssi=None, last_seen=None, enabled=True)


# ---- decide(): 六情境 ----

def test_decide_first_detection():
    """首次偵測：從未見過（last_seen=None），probe 成功 → 立刻判定在場。"""
    new = presence.decide(True, -50, -75, NEVER, NOW, 150)
    assert new.present is True
    assert new.last_seen == NOW


def test_decide_continuous_presence():
    """持續在場：上一輪已經 present，這輪 probe 又成功 → 維持在場，last_seen 推進。"""
    prev = PresenceState(present=True, rssi=-50, last_seen=NOW - timedelta(seconds=45),
                         enabled=True)
    new = presence.decide(True, -50, -75, prev, NOW, 150)
    assert new.present is True
    assert new.last_seen == NOW


def test_decide_just_left_still_in_grace():
    """剛離開仍在寬限：probe 失敗，但距上次見到還不到 grace_sec → 仍判定在場，
    last_seen 維持不變（不是又見到了，只是還沒判定離開）。"""
    last_seen = NOW - timedelta(seconds=100)
    prev = PresenceState(present=True, rssi=-50, last_seen=last_seen, enabled=True)
    new = presence.decide(False, None, -75, prev, NOW, 150)
    assert new.present is True
    assert new.last_seen == last_seen


def test_decide_exceeded_grace():
    """超過寬限：probe 失敗，距上次見到已經超過 grace_sec → 判定不在場。"""
    last_seen = NOW - timedelta(seconds=200)
    prev = PresenceState(present=True, rssi=-50, last_seen=last_seen, enabled=True)
    new = presence.decide(False, None, -75, prev, NOW, 150)
    assert new.present is False


def test_decide_rssi_below_threshold():
    """RSSI 低於門檻：probe 雖然成功，但訊號太弱視同沒偵測到 —— 若同時已超過寬限，
    判定不在場。"""
    last_seen = NOW - timedelta(seconds=200)
    prev = PresenceState(present=True, rssi=-50, last_seen=last_seen, enabled=True)
    new = presence.decide(True, -90, -75, prev, NOW, 150)
    assert new.present is False


def test_decide_rssi_none_ignores_threshold():
    """RSSI 為 None（裝置探測得到但拿不到訊號強度）：不因為拿不到 RSSI 就否決，
    probe 成功即視為在場。"""
    new = presence.decide(True, None, -75, NEVER, NOW, 150)
    assert new.present is True
    assert new.last_seen == NOW


# ---- probe_once() ----

def test_probe_once_missing_binary_does_not_raise():
    """環境沒裝 l2ping（FileNotFoundError）—— 不得拋例外，回 (False, None)。"""
    def boom(*a, **k):
        raise FileNotFoundError("l2ping: command not found")

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=boom)
    assert present is False
    assert rssi is None


def test_probe_once_timeout_does_not_raise():
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="l2ping", timeout=2)

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=boom)
    assert present is False
    assert rssi is None


def test_probe_once_success_parses_rssi():
    calls = []

    class Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "l2ping":
            return Result(0)
        return Result(0, stdout="RSSI return value: -58")

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
    assert present is True
    assert rssi == -58
    assert calls[0][0] == "l2ping"
    assert calls[1][0] == "hcitool"


def test_probe_once_ping_fails_reports_absent():
    class Result:
        returncode = 1
        stdout = ""

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF",
                                        runner=lambda *a, **k: Result())
    assert present is False
    assert rssi is None


def test_probe_once_rssi_unavailable_still_present():
    """hcitool 不存在時，present 判定不受影響，只是 rssi 拿不到。"""
    class PingOk:
        returncode = 0
        stdout = ""

    def fake_runner(cmd, **kwargs):
        if cmd[0] == "l2ping":
            return PingOk()
        raise FileNotFoundError("hcitool: command not found")

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
    assert present is True
    assert rssi is None


# ---- start_presence_thread() ----
# 2026-07-27 語意翻轉：執行緒永遠啟動、每輪自查 enabled/mac——開機時 mac 未設
# 就不建 thread 的舊行為，會讓使用者事後配好裝置/打開開關卻要重開機才生效
# （實機回報「開了沒反應」的根因之一）。


def test_start_always_spawns_even_when_disabled():
    state = AppState()
    settings = Settings()
    settings.presence_enabled = False
    settings.presence_mac = "AA:BB:CC:DD:EE:FF"
    import threading
    assert presence.start_presence_thread(state, settings, threading.Lock()) is True


def test_start_always_spawns_even_when_mac_empty():
    state = AppState()
    settings = Settings()
    settings.presence_enabled = True
    settings.presence_mac = ""
    import threading
    assert presence.start_presence_thread(state, settings, threading.Lock()) is True


# ---------------------------------------------------------------- 久坐提示

from deskbar.presence import (SEDENTARY_AFTER_S, SEDENTARY_GAP_S,
                              SEDENTARY_HINT_S, SedentaryTracker)


def test_sedentary_fires_after_an_hour():
    tr = SedentaryTracker()
    tr.update(True, 0.0)
    tr.update(True, SEDENTARY_AFTER_S - 1)
    assert not tr.hint_active(SEDENTARY_AFTER_S - 1), "未滿一小時不提示"
    tr.update(True, SEDENTARY_AFTER_S)
    assert tr.hint_active(SEDENTARY_AFTER_S), "滿一小時出提示"
    assert not tr.hint_active(SEDENTARY_AFTER_S + SEDENTARY_HINT_S + 1), \
        "提示三分鐘後自己消失"


def test_sedentary_short_gap_does_not_reset():
    tr = SedentaryTracker()
    tr.update(True, 0.0)
    tr.update(False, 1800.0)                       # 倒水 3 分鐘
    tr.update(True, 1800.0 + 180)
    tr.update(True, SEDENTARY_AFTER_S)
    assert tr.hint_active(SEDENTARY_AFTER_S), "短暫離席不重置計時"


def test_sedentary_real_break_resets():
    tr = SedentaryTracker()
    tr.update(True, 0.0)
    tr.update(False, 1800.0)
    tr.update(False, 1800.0 + SEDENTARY_GAP_S)     # 離席滿 5 分鐘＝真休息
    tr.update(True, 1800.0 + SEDENTARY_GAP_S + 1)  # 回座重新起算
    tr.update(True, SEDENTARY_AFTER_S + 1)
    assert not tr.hint_active(SEDENTARY_AFTER_S + 1), "真休息後計時重來"


def test_sedentary_hourly_rhythm_and_reset():
    tr = SedentaryTracker()
    tr.update(True, 0.0)
    tr.update(True, SEDENTARY_AFTER_S)             # 第一次提示
    t2 = SEDENTARY_AFTER_S * 2
    tr.update(True, t2)                            # 再滿一小時 → 第二次
    assert tr.hint_active(t2), "約每小時一次的節奏"
    tr.reset()
    assert not tr.hint_active(t2), "reset 收掉提示"


def test_sedentary_hint_renders_in_panel():
    import pygame
    from deskbar.store import AppState
    from deskbar.config import Settings
    from deskbar.ui import dashboard
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime(2026, 8, 3, 15, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    snap = AppState().snapshot()
    a = pygame.Surface((1920, 480)); b = pygame.Surface((1920, 480))
    dashboard.render_panel_only(a, snap, Settings(), now, sedentary=False)
    dashboard.render_panel_only(b, snap, Settings(), now, sedentary=True)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB"), \
        "sedentary=True 要多畫一行提示"


# ---------------------------------------------------------------- 探測退避與 Push 過期測試 (2026-08-04)

def test_backoff_delay_boundaries():
    assert presence.backoff_delay(-1) == 0
    assert presence.backoff_delay(0) == 0
    assert presence.backoff_delay(1) == 0
    assert presence.backoff_delay(2) == 30
    assert presence.backoff_delay(3) == 60
    assert presence.backoff_delay(4) == 120
    assert presence.backoff_delay(5) == 300
    assert presence.backoff_delay(6) == 600
    assert presence.backoff_delay(7) == 1800
    assert presence.backoff_delay(8) == 1800
    assert presence.backoff_delay(99) == 1800


def test_next_sleep_combines_interval_and_backoff():
    assert presence.next_sleep(45, 0) == 45
    assert presence.next_sleep(45, 1) == 45
    assert presence.next_sleep(45, 2) == 75
    assert presence.next_sleep(45, 6) == 645
    assert presence.next_sleep(45, 7) == 1845


def test_probe_once_lock_contention_returns_false_and_skips_runner():
    runner_called = False

    def fake_runner(*a, **k):
        nonlocal runner_called
        runner_called = True

    with presence._PROBE_LOCK:
        present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
        assert present is False
        assert rssi is None
        assert not runner_called, "鎖被佔用時不得呼叫 runner 重疊送連線請求"


def test_expire_push_behavior():
    t0 = datetime(2026, 8, 4, 12, 0, tzinfo=TZ)
    st_present = PresenceState(present=True, rssi=-60, last_seen=t0, enabled=True)

    # 未過期：維持在場
    t1 = t0 + timedelta(seconds=899)
    st1 = presence.expire_push(st_present, t1, 900)
    assert st1.present is True
    assert st1.last_seen == t0

    # 已過期：轉為不在場
    t2 = t0 + timedelta(seconds=900)
    st2 = presence.expire_push(st_present, t2, 900)
    assert st2.present is False

    # last_seen 為 None：視為不在場
    st_no_last_seen = PresenceState(present=True, rssi=-60, last_seen=None, enabled=True)
    st3 = presence.expire_push(st_no_last_seen, t0, 900)
    assert st3.present is False

    # 已經是不在場：原樣回傳
    st_absent = PresenceState(present=False, rssi=None, last_seen=t0, enabled=True)
    st4 = presence.expire_push(st_absent, t0 + timedelta(seconds=9999), 900)
    assert st4 == st_absent


# ---------------------------------------------------------------- 藍牙控制器保護與自動復原 (2026-08-05)

def test_probe_once_calls_hcitool_dc_on_l2ping_failure():
    calls = []

    class Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "l2ping":
            return Result(1)
        return Result(0)

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
    assert present is False
    assert rssi is None
    assert len(calls) == 2
    assert calls[0][0] == "l2ping"
    assert calls[1][:3] == ["hcitool", "dc", "AA:BB:CC:DD:EE:FF"]


def test_probe_once_does_not_call_hcitool_dc_on_l2ping_success():
    calls = []

    class Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "l2ping":
            return Result(0)
        return Result(0, stdout="RSSI return value: -50")

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
    assert present is True
    assert rssi == -50
    assert len(calls) == 2
    assert calls[0][0] == "l2ping"
    assert calls[1][0] == "hcitool"
    assert calls[1][1] == "rssi"


def test_probe_once_dc_exception_returns_false_and_none():
    def fake_runner(cmd, **kwargs):
        if cmd[0] == "l2ping":
            raise subprocess.TimeoutExpired(cmd="l2ping", timeout=2)
        if cmd[0] == "hcitool" and cmd[1] == "dc":
            raise RuntimeError("dc command crashed")
        return None

    present, rssi = presence.probe_once("AA:BB:CC:DD:EE:FF", runner=fake_runner)
    assert present is False
    assert rssi is None


def test_adapter_healthy_cases():
    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    # rc=0 且正常輸出 → True
    def runner_ok(cmd, **kwargs):
        return Result(0, stdout="hci0:\tType: Primary  Bus: UART\n\tBD Address: 00:11:22:33:44:55\n\tUP RUNNING\n")
    assert presence.adapter_healthy(runner=runner_ok) is True

    # 輸出含 "Can't init device" → False
    def runner_cant_init(cmd, **kwargs):
        return Result(1, stdout="Can't init device hci0: Connection timed out (110)\n")
    assert presence.adapter_healthy(runner=runner_cant_init) is False

    # rc=0 但輸出含 "Can't init device" → False
    def runner_cant_init_rc0(cmd, **kwargs):
        return Result(0, stdout="Can't init device hci0: Device or resource busy\n")
    assert presence.adapter_healthy(runner=runner_cant_init_rc0) is False

    # 逾時 → False
    def runner_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="hciconfig", timeout=5)
    assert presence.adapter_healthy(runner=runner_timeout) is False

    # FileNotFoundError → False
    def runner_fnf(cmd, **kwargs):
        raise FileNotFoundError("hciconfig: command not found")
    assert presence.adapter_healthy(runner=runner_fnf) is False


def test_try_recover_adapter_cases(monkeypatch):
    monkeypatch.setattr(presence._time, "sleep", lambda s: None)

    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    # 1. 第一段就恢復 → True 且沒有跑第二段
    calls_stage1 = []
    def runner_stage1_ok(cmd, **kwargs):
        calls_stage1.append(cmd)
        if cmd[0] == "sudo" and cmd[2] == "systemctl":
            return Result(0)
        if cmd[0] == "hciconfig":
            return Result(0, stdout="hci0: UP RUNNING")
        return Result(0)

    res1 = presence.try_recover_adapter(runner=runner_stage1_ok)
    assert res1 is True
    cmds_run = [c[0] if c[0] != "sudo" else f"sudo {c[2]}" for c in calls_stage1]
    assert "sudo systemctl" in cmds_run
    assert "sudo hciconfig" not in cmds_run

    # 2. 第一段失敗第二段成功 → True
    calls_stage2 = []
    hciconfig_calls = 0
    def runner_stage2_ok(cmd, **kwargs):
        nonlocal hciconfig_calls
        calls_stage2.append(cmd)
        if cmd[0] == "sudo" and cmd[2] == "systemctl":
            return Result(0)
        if cmd[0] == "hciconfig":
            hciconfig_calls += 1
            if hciconfig_calls == 1:
                return Result(1, stdout="Can't init device")  # 第一段檢查失敗
            return Result(0, stdout="hci0: UP RUNNING")       # 第二段檢查成功
        if cmd[0] == "sudo" and cmd[2] == "hciconfig":
            return Result(0)
        return Result(0)

    res2 = presence.try_recover_adapter(runner=runner_stage2_ok)
    assert res2 is True
    cmds_run2 = [c[0] if c[0] != "sudo" else f"sudo {c[2]}" for c in calls_stage2]
    assert "sudo systemctl" in cmds_run2
    assert "sudo hciconfig" in cmds_run2

    # 3. 兩段都失敗 → False
    def runner_both_fail(cmd, **kwargs):
        if cmd[0] == "hciconfig":
            return Result(1, stdout="Can't init device")
        return Result(0)

    assert presence.try_recover_adapter(runner=runner_both_fail) is False

    # 4. 任何例外 → False 不拋出
    def runner_raises(cmd, **kwargs):
        raise OSError("Permission denied")

    assert presence.try_recover_adapter(runner=runner_raises) is False


