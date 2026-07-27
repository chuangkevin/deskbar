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
