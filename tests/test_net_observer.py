import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBSERVER_SCRIPT = ROOT / "deploy" / "net-observer.sh"
PROBE_SCRIPT = ROOT / "tools" / "deskbar_net_probe.py"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    _write_executable(
        bin_dir / "logger",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("LOGGER " + " ".join(sys.argv[1:]) + "\\n")
""",
    )

    _write_executable(
        bin_dir / "nmcli",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("NMCLI " + " ".join(sys.argv[1:]) + "\\n")
print(os.environ.get("DESKBAR_TEST_NMCLI_OUT", "wlan0:connected\\n"))
""",
    )

    _write_executable(
        bin_dir / "ip",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("IP " + " ".join(sys.argv[1:]) + "\\n")
print(os.environ.get("DESKBAR_TEST_IP_OUT", "default via 192.168.1.1 dev wlan0\\n"))
""",
    )

    _write_executable(
        bin_dir / "getent",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("GETENT " + " ".join(sys.argv[1:]) + "\\n")
rc = int(os.environ.get("DESKBAR_TEST_GETENT_RC", "0"))
if rc == 0:
    print("93.184.216.34 desk.sisihome.org")
sys.exit(rc)
""",
    )

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("CURL " + " ".join(sys.argv[1:]) + "\\n")
url = sys.argv[-1] if sys.argv else ""
if "1.1.1.1" in url:
    sys.exit(int(os.environ.get("DESKBAR_TEST_PUBLIC_CURL_RC", "0")))
else:
    sys.exit(int(os.environ.get("DESKBAR_TEST_LOCAL_CURL_RC", "0")))
""",
    )

    return bin_dir


def _run_observer(tmp_path: Path, **env_overrides):
    log_file = tmp_path / "observer_cmd.log"
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{_fake_bin(tmp_path)}:{env['PATH']}",
            "DESKBAR_TEST_LOG": str(log_file),
            "RUNTIME_DIRECTORY": str(run_dir),
        }
    )
    env.update(env_overrides)
    proc = subprocess.run(
        ["bash", str(OBSERVER_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc, log_file, run_dir


def test_pi_observer_normal_and_degraded_state_change_logging(tmp_path):
    # 1st run: Normal state -> logs state change once
    proc, log_file, run_dir = _run_observer(tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""
    cmd_log = log_file.read_text(encoding="utf-8")
    assert "LOGGER -t deskbar-net-observer wlan0_connected=true route_via_wlan0=true dns_resolution=true public_ip_http=true deskbar_local_http=true" in cmd_log

    # 2nd run: Normal state unchanged -> should NOT log to logger again
    log_file.unlink()
    proc, log_file, _ = _run_observer(tmp_path)
    assert proc.returncode == 0
    cmd_log_2 = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "LOGGER" not in cmd_log_2

    # 3rd run: Degraded state (public_ip_http=false) -> logs state change once
    if log_file.exists():
        log_file.unlink()
    proc, log_file, _ = _run_observer(tmp_path, DESKBAR_TEST_PUBLIC_CURL_RC="7")
    assert proc.returncode == 0
    cmd_log_3 = log_file.read_text(encoding="utf-8")
    assert "LOGGER -t deskbar-net-observer wlan0_connected=true route_via_wlan0=true dns_resolution=true public_ip_http=false deskbar_local_http=true" in cmd_log_3

    # 4th run: Degraded state unchanged -> should NOT log again
    log_file.unlink()
    proc, log_file, _ = _run_observer(tmp_path, DESKBAR_TEST_PUBLIC_CURL_RC="7")
    assert proc.returncode == 0
    cmd_log_4 = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "LOGGER" not in cmd_log_4


def test_pi_observer_executes_no_recovery_commands(tmp_path):
    proc, log_file, _ = _run_observer(tmp_path, DESKBAR_TEST_PUBLIC_CURL_RC="7", DESKBAR_TEST_GETENT_RC="2")
    assert proc.returncode == 0
    cmd_log = log_file.read_text(encoding="utf-8")

    forbidden_cmds = ["connection up", "radio", "systemctl", "restart", "sudo"]
    for forbidden in forbidden_cmds:
        assert forbidden not in cmd_log


def test_mac_probe_once_reports_two_states_and_logs_on_change(tmp_path):
    log_file = tmp_path / "probe.log"
    env = os.environ.copy()
    env.update(
        {
            "DESKBAR_NET_PROBE_LOG": str(log_file),
            "PI_TAILNET_URL": "http://127.0.0.1:9999",
            "DESK_SISHOME_URL": "http://127.0.0.1:9999",
        }
    )

    # 1st run: Probe --once when unreachable
    proc = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT), "--once"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert log_file.exists()
    content_1 = log_file.read_text(encoding="utf-8")
    assert "pi_tailnet_http=false desk_sisihome_https=false" in content_1
    assert len(content_1.strip().splitlines()) == 1

    # 2nd run: Probe --once unchanged -> no new line written
    proc = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT), "--once"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    content_2 = log_file.read_text(encoding="utf-8")
    assert len(content_2.strip().splitlines()) == 1

    # 3rd run: Simulate state change by mocking probe_endpoint
    with patch("tools.deskbar_net_probe.probe_endpoint") as mock_probe:
        mock_probe.side_effect = [True, True]
        from tools import deskbar_net_probe
        last_state = deskbar_net_probe.read_last_state(log_file)
        deskbar_net_probe.run_probe("http://dummy1", "http://dummy2", log_file, last_state)

    content_3 = log_file.read_text(encoding="utf-8")
    lines = content_3.strip().splitlines()
    assert len(lines) == 2
    assert "pi_tailnet_http=true desk_sisihome_https=true" in lines[1]


def test_mac_probe_rejects_non_positive_interval():
    proc = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT), "--interval", "0", "--once"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "greater than zero" in proc.stderr


def test_mac_probe_log_does_not_contain_sensitive_info(tmp_path):
    log_file = tmp_path / "probe.log"
    env = os.environ.copy()
    secret_url = "http://100.98.35.59:8080/secret-path"
    env.update(
        {
            "DESKBAR_NET_PROBE_LOG": str(log_file),
            "PI_TAILNET_URL": secret_url,
            "DESK_SISHOME_URL": "https://desk.sisihome.org/secret-header",
        }
    )

    proc = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT), "--once"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    log_text = log_file.read_text(encoding="utf-8")

    for prohibited in ["100.98.35.59", "desk.sisihome.org", "secret-path", "secret-header", "http://", "https://"]:
        assert prohibited not in log_text
