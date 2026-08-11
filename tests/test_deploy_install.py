import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "deploy" / "install.sh"
MAKEFILE = ROOT / "Makefile"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _setup_fake_environment(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "command.log"

    # Fake sudo binary to execute inner commands and log
    sudo_script = """#!/usr/bin/env python3
import os, sys, subprocess
args = sys.argv[1:]
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("SUDO " + " ".join(args) + "\\n")
res = subprocess.run(args)
sys.exit(res.returncode)
"""
    _write_executable(bin_dir / "sudo", sudo_script)

    dummy_log_binaries = ["apt-get", "setcap", "nmcli", "iw", "systemctl", "systemd-tmpfiles", "l2ping"]
    for bin_name in dummy_log_binaries:
        body = f"""#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("{bin_name.upper()} " + " ".join(sys.argv[1:]) + "\\n")
"""
        _write_executable(bin_dir / bin_name, body)

    # Fake DESKBAR_DEPLOY_HOME
    fake_home = tmp_path / "deskbar_home"
    fake_home.mkdir()
    deploy_dir = fake_home / "deploy"
    deploy_dir.mkdir()

    # Copy files from real deploy directory
    for item in (ROOT / "deploy").iterdir():
        if item.is_file():
            shutil.copy2(item, deploy_dir / item.name)

    (fake_home / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # Fake targets
    fake_systemd_dir = tmp_path / "systemd_system"
    fake_systemd_dir.mkdir()
    fake_watchdog_path = tmp_path / "usr_bin" / "deskbar-net-watchdog.sh"
    fake_watchdog_path.parent.mkdir()

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DESKBAR_TEST_LOG"] = str(log_file)
    env["DESKBAR_DEPLOY_HOME"] = str(fake_home)
    env["DESKBAR_DEPLOY_SYSTEMD_DIR"] = str(fake_systemd_dir)
    env["DESKBAR_DEPLOY_WATCHDOG_PATH"] = str(fake_watchdog_path)

    return fake_home, fake_systemd_dir, fake_watchdog_path, log_file, env


def test_runtime_only_success(tmp_path):
    fake_home, fake_systemd_dir, fake_watchdog_path, log_file, env = _setup_fake_environment(tmp_path)

    # Create fake .venv with dummy pip executable
    fake_venv_bin = fake_home / ".venv" / "bin"
    fake_venv_bin.mkdir(parents=True)
    _write_executable(
        fake_venv_bin / "pip",
        """#!/usr/bin/env python3
import os, sys
with open(os.environ["DESKBAR_TEST_LOG"], "a", encoding="utf-8") as f:
    f.write("PIP " + " ".join(sys.argv[1:]) + "\\n")
""",
    )

    proc = subprocess.run(
        ["bash", str(fake_home / "deploy" / "install.sh"), "--runtime-only"],
        cwd=fake_home,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert (fake_systemd_dir / "deskbar.service").exists()
    assert fake_watchdog_path.exists()
    assert (fake_systemd_dir / "deskbar-net-watchdog.service").exists()
    assert (fake_systemd_dir / "deskbar-net-watchdog.timer").exists()

    log_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "PIP install -q -r requirements.txt" in log_content
    assert "SYSTEMCTL daemon-reload" in log_content
    assert "SYSTEMCTL enable --now deskbar-net-watchdog.timer" in log_content

    # Ensure forbidden operations were NOT logged
    for forbidden in ["APT-GET", "SETCAP", "NMCLI", "IW", "SYSTEMD-TMPFILES"]:
        assert forbidden not in log_content, f"Found forbidden execution '{forbidden}' in log:\n{log_content}"
    assert "journald" not in log_content.lower()


def test_runtime_only_missing_venv_fails(tmp_path):
    fake_home, _, _, log_file, env = _setup_fake_environment(tmp_path)

    proc = subprocess.run(
        ["bash", str(fake_home / "deploy" / "install.sh"), "--runtime-only"],
        cwd=fake_home,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    combined_output = proc.stdout + proc.stderr
    assert "bootstrap" in combined_output.lower() or ".venv" in combined_output.lower()

    log_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "APT-GET" not in log_content


def test_invalid_argument_fails(tmp_path):
    fake_home, _, _, _, env = _setup_fake_environment(tmp_path)

    proc = subprocess.run(
        ["bash", str(fake_home / "deploy" / "install.sh"), "--unknown-option"],
        cwd=fake_home,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "Usage:" in proc.stderr or "Usage:" in proc.stdout


def test_makefile_deploy_and_bootstrap_contracts():
    makefile_text = MAKEFILE.read_text(encoding="utf-8")

    assert "install.sh --runtime-only" in makefile_text
    assert "bootstrap:" in makefile_text
    lines = makefile_text.splitlines()
    bootstrap_idx = next(i for i, line in enumerate(lines) if line.startswith("bootstrap:"))
    bootstrap_recipe = "\n".join(lines[bootstrap_idx + 1 : bootstrap_idx + 3])
    assert "install.sh" in bootstrap_recipe
    assert "--runtime-only" not in bootstrap_recipe
