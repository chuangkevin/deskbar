"""Focused OpenAI activity detection regressions for usage_push_demo."""
import importlib.util
import os
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


def _load_demo_module():
    path = TOOLS_DIR / "usage_push_demo.py"
    spec = importlib.util.spec_from_file_location("usage_push_demo_activity", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _set_mtime(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_openai_activity_mtime_discovers_dynamic_codex_wal_artifacts(tmp_path):
    demo = _load_demo_module()
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()

    legacy_auth = tmp_path / "auth.json"
    legacy_auth.touch()
    _set_mtime(legacy_auth, 1000.0)

    unrelated = codex_dir / "unrelated.sqlite-wal"
    unrelated.touch()
    _set_mtime(unrelated, 3000.0)

    matching_directory = codex_dir / "queue_1.sqlite-wal"
    matching_directory.mkdir()
    _set_mtime(matching_directory, 4000.0)

    paths = (legacy_auth, tmp_path / "missing-history.jsonl")
    glob_patterns = (
        str(codex_dir / "logs_*.sqlite-wal"),
        str(codex_dir / "thread_history_*.sqlite-wal"),
        str(codex_dir / "queue_*.sqlite-wal"),
        str(codex_dir / "state_*.sqlite-wal"),
    )

    assert demo._latest_oa_activity_mtime(paths, glob_patterns) == 1000.0
    assert demo._oa_activity_mtime_changed(paths, glob_patterns) is False

    _set_mtime(unrelated, 5000.0)
    assert demo._oa_activity_mtime_changed(paths, glob_patterns) is False

    logs_wal = codex_dir / "logs_1.sqlite-wal"
    logs_wal.touch()
    _set_mtime(logs_wal, 2000.0)
    assert demo._oa_activity_mtime_changed(paths, glob_patterns) is True

    rotated_wal = codex_dir / "thread_history_2.sqlite-wal"
    rotated_wal.touch()
    _set_mtime(rotated_wal, 2500.0)
    assert demo._oa_activity_mtime_changed(paths, glob_patterns) is True
