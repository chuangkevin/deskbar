import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "net-watchdog.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "logger",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("LOGGER " + " ".join(sys.argv[1:]) + "\\n")
""",
    )
    _write_executable(
        bin_dir / "date",
        """#!/usr/bin/env python3
import os, sys
if sys.argv[1:] == ["+%s"]:
    print(os.environ.get("DESKBAR_TEST_NOW", "1000"))
else:
    raise SystemExit(2)
""",
    )
    _write_executable(
        bin_dir / "sleep",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("SLEEP " + " ".join(sys.argv[1:]) + "\\n")
""",
    )
    _write_executable(
        bin_dir / "nmcli",
        """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
log = os.environ["DESKBAR_TEST_LOG"]
with open(log, "a", encoding="utf-8") as f:
    f.write("NMCLI " + " ".join(args) + "\\n")
if args == ["-t", "-f", "DEVICE,STATE", "dev"]:
    print(os.environ.get("DESKBAR_TEST_NMCLI_DEV_OUT", ""), end="")
    raise SystemExit(int(os.environ.get("DESKBAR_TEST_NMCLI_DEV_RC", "0")))
if args == ["-t", "-f", "NAME,TYPE", "connection", "show"]:
    print(os.environ.get("DESKBAR_TEST_NMCLI_CONNECTIONS", ""), end="")
    raise SystemExit(0)
if len(args) >= 6 and args[:5] == ["-w", "25", "connection", "up", "id"]:
    conn = args[5]
    ok = os.environ.get("DESKBAR_TEST_UP_SUCCESS", "")
    raise SystemExit(0 if conn == ok else 10)
if args == ["radio", "wifi", "off"] or args == ["radio", "wifi", "on"]:
    raise SystemExit(0)
raise SystemExit(99)
""",
    )
    return bin_dir


def _run_watchdog(tmp_path: Path, **env_overrides):
    log_file = tmp_path / "watchdog.log"
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_bin(tmp_path)}:{env['PATH']}",
            "DESKBAR_TEST_LOG": str(log_file),
            "DESKBAR_WATCHDOG_FAIL_FILE": str(run_dir / "fail"),
            "DESKBAR_WATCHDOG_COOLDOWN_FILE": str(run_dir / "cooldown"),
            "DESKBAR_WATCHDOG_STATE_FILE": str(run_dir / "state"),
            "DESKBAR_WATCHDOG_ACTION_FILE": str(run_dir / "actions"),
            "DESKBAR_WATCHDOG_FAIL_THRESHOLD": "5",
            "DESKBAR_WATCHDOG_COOLDOWN_S": "600",
            "DESKBAR_TEST_NOW": "1000",
        }
    )
    env.update(env_overrides)
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc, log_file, run_dir


def test_connected_clears_fail_without_rescue(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir()
    fail_file.write_text("4\n", encoding="utf-8")

    proc, log_file, _ = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:connected\np2p-dev-wlan0:disconnected\n",
    )

    assert proc.returncode == 0
    assert not fail_file.exists()
    log = log_file.read_text(encoding="utf-8")
    assert "狀態轉換 state=CONNECTED" in log
    assert "radio wifi off" not in log


def test_progressing_clears_fail_without_rescue(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir()
    fail_file.write_text("4\n", encoding="utf-8")

    proc, log_file, _ = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:ip-config\n",
    )

    assert proc.returncode == 0
    assert not fail_file.exists()
    log = log_file.read_text(encoding="utf-8")
    assert "狀態轉換 state=PROGRESSING" in log
    assert "radio wifi off" not in log


def test_dead_below_threshold_only_increments_fail_count(tmp_path):
    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:disconnected\n",
    )

    assert proc.returncode == 0
    assert (run_dir / "fail").read_text(encoding="utf-8").strip() == "1"
    assert not (run_dir / "cooldown").exists()
    log = log_file.read_text(encoding="utf-8")
    assert "連線狀態 DEAD (1/5)" in log
    assert "radio wifi off" not in log


def test_fifth_dead_tries_profiles_before_radio_restart(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir()
    fail_file.write_text("4\n", encoding="utf-8")

    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:disconnected\n",
        DESKBAR_TEST_NMCLI_CONNECTIONS="Home:802-11-wireless\nPhone:802-11-wireless\n",
        DESKBAR_TEST_UP_SUCCESS="Phone",
    )

    assert proc.returncode == 0
    assert not fail_file.exists()
    assert (run_dir / "cooldown").read_text(encoding="utf-8").strip() == "1000"
    log = log_file.read_text(encoding="utf-8")
    assert "第一段救援候選 WiFi profile 數量=2" in log
    assert "啟動連線 Home 失敗 rc=10" in log
    assert "成功啟動連線 Phone" in log
    assert "radio wifi off" not in log


def test_fifth_dead_restarts_radio_when_all_profiles_fail(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir()
    fail_file.write_text("4\n", encoding="utf-8")

    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:disconnected\n",
        DESKBAR_TEST_NMCLI_CONNECTIONS="Home:802-11-wireless\n",
    )

    assert proc.returncode == 0
    assert (run_dir / "cooldown").read_text(encoding="utf-8").strip() == "1000"
    log = log_file.read_text(encoding="utf-8")
    assert "近 21600 秒 radio_restart 次數=1" in log
    assert "NMCLI radio wifi off" in log
    assert "SLEEP 5" in log
    assert "NMCLI radio wifi on" in log


def test_nmcli_device_error_is_logged_and_keeps_dead_path(tmp_path):
    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="NetworkManager is not running\n",
        DESKBAR_TEST_NMCLI_DEV_RC="8",
    )

    assert proc.returncode == 0
    assert (run_dir / "fail").read_text(encoding="utf-8").strip() == "1"
    log = log_file.read_text(encoding="utf-8")
    assert "nmcli 裝置狀態讀取失敗 rc=8" in log
    assert "連線狀態 DEAD (1/5)。nmcli_rc=8" in log


def test_cooldown_exits_before_reading_nmcli(tmp_path):
    cooldown = tmp_path / "run" / "cooldown"
    cooldown.parent.mkdir()
    cooldown.write_text("900\n", encoding="utf-8")

    proc, log_file, _ = _run_watchdog(tmp_path)

    assert proc.returncode == 0
    assert not log_file.exists()


def test_radio_restart_circuit_breaker_when_max_restarts_reached(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir(parents=True, exist_ok=True)
    fail_file.write_text("4\n", encoding="utf-8")

    action_file = tmp_path / "run" / "actions"
    action_file.write_text("800 radio_restart\n900 radio_restart\n", encoding="utf-8")

    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:disconnected\n",
        DESKBAR_TEST_NMCLI_CONNECTIONS="Home:802-11-wireless\n",
    )

    assert proc.returncode == 0
    log = log_file.read_text(encoding="utf-8")
    assert "第一段救援候選 WiFi profile 數量=1" in log
    assert "啟動連線 Home 失敗" in log
    assert "radio 保護熔斷" in log
    assert "近 21600 秒" in log
    assert "已有 2/2 次" in log
    assert "NMCLI radio wifi off" not in log
    assert "SLEEP 5" not in log
    assert "NMCLI radio wifi on" not in log
    assert action_file.read_text(encoding="utf-8") == "800 radio_restart\n900 radio_restart\n"
    assert (run_dir / "cooldown").read_text(encoding="utf-8").strip() == "1000"


def test_radio_restart_outside_window_does_not_trigger_breaker(tmp_path):
    fail_file = tmp_path / "run" / "fail"
    fail_file.parent.mkdir(parents=True, exist_ok=True)
    fail_file.write_text("4\n", encoding="utf-8")

    action_file = tmp_path / "run" / "actions"
    action_file.write_text("700 radio_restart\n800 radio_restart\n", encoding="utf-8")

    proc, log_file, run_dir = _run_watchdog(
        tmp_path,
        DESKBAR_WATCHDOG_ACTION_WINDOW_S="100",
        DESKBAR_TEST_NMCLI_DEV_OUT="wlan0:disconnected\n",
        DESKBAR_TEST_NMCLI_CONNECTIONS="Home:802-11-wireless\n",
    )

    assert proc.returncode == 0
    log = log_file.read_text(encoding="utf-8")
    assert "第一段救援候選 WiFi profile 數量=1" in log
    assert "啟動連線 Home 失敗" in log
    assert "radio 保護熔斷" not in log
    assert "NMCLI radio wifi off" in log
    assert "SLEEP 5" in log
    assert "NMCLI radio wifi on" in log
    assert "近 100 秒 radio_restart 次數=1" in log
    assert action_file.read_text(encoding="utf-8") == "1000 radio_restart\n"
    assert (run_dir / "cooldown").read_text(encoding="utf-8").strip() == "1000"
