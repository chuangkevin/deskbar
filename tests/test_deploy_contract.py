import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
WORK_SESSIONS_LABEL = "com.deskbar.work-sessions"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _setup_fake_commands(tmp_path: Path, *, launchctl_loaded: bool, deploy_tools: bool = False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "commands.jsonl"

    launchctl_script = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(["launchctl", *sys.argv[1:]]) + "\\n")

if sys.argv[1:2] == ["print"]:
    sys.exit(0 if os.environ.get("DESKBAR_TEST_LAUNCHCTL_LOADED") == "1" else 113)
sys.exit(0)
"""
    _write_executable(bin_dir / "launchctl", launchctl_script)

    if deploy_tools:
        for command in ("rsync", "ssh"):
            script = f"""#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(["{command}", *sys.argv[1:]]) + "\\n")
sys.exit(0)
"""
            _write_executable(bin_dir / command, script)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DESKBAR_TEST_LOG"] = str(log_file)
    env["DESKBAR_TEST_LAUNCHCTL_LOADED"] = "1" if launchctl_loaded else "0"
    return log_file, env


def _run_make(target: str, tmp_path: Path, *, launchctl_loaded: bool = True, deploy_tools: bool = False):
    log_file, env = _setup_fake_commands(tmp_path, launchctl_loaded=launchctl_loaded, deploy_tools=deploy_tools)
    command = ["make", "-f", str(MAKEFILE), target]
    if target == "deploy":
        command.extend([
            "PI=pi@test.local",
            "KEY=/tmp/test-key",
            "DEST=/tmp/deskbar-test",
        ])
    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    commands = []
    if log_file.exists():
        commands = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    return proc, commands


def _agent_domain() -> str:
    return f"gui/{os.getuid()}/{WORK_SESSIONS_LABEL}"


def test_deploy_restarts_work_sessions_agent_after_successful_pi_restart(tmp_path):
    proc, commands = _run_make("deploy", tmp_path, deploy_tools=True)

    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    ssh_commands = [command for command in commands if command[0] == "ssh"]
    assert ssh_commands, commands
    assert "install.sh --runtime-only && sudo systemctl restart deskbar" in ssh_commands[0][-1]
    assert commands[-2:] == [
        ["launchctl", "print", _agent_domain()],
        ["launchctl", "kickstart", "-k", _agent_domain()],
    ]


def test_restart_work_sessions_agent_prints_then_kickstarts_loaded_agent(tmp_path):
    proc, commands = _run_make("restart-work-sessions-agent", tmp_path, launchctl_loaded=True)

    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert commands == [
        ["launchctl", "print", _agent_domain()],
        ["launchctl", "kickstart", "-k", _agent_domain()],
    ]


def test_restart_work_sessions_agent_skips_unloaded_agent_successfully(tmp_path):
    proc, commands = _run_make("restart-work-sessions-agent", tmp_path, launchctl_loaded=False)

    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    combined_output = (proc.stdout + proc.stderr).lower()
    assert "not loaded" in combined_output
    assert "skip" in combined_output
    assert commands == [["launchctl", "print", _agent_domain()]]
