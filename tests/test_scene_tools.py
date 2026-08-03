from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from deskbar.config import SCENE_KEYS
from tools.benchmark_scenes import (
    DEFAULT_MEASURED,
    DEFAULT_WARMUPS,
    BenchmarkRequest,
    benchmark_scenes,
)
from tools.render_scene_review import ReviewRequest, render_review, resolve_scene_selector


def test_render_review_writes_static_motion_contacts_and_metrics(tmp_path: Path) -> None:
    # Given
    request = ReviewRequest(("stars",), tmp_path, "all")

    # When
    paths = render_review(request)

    # Then
    relative = {path.relative_to(tmp_path).as_posix() for path in paths}
    assert {f"stars/dashboard/stars_{label}.png" for label in ("night", "dawn", "day")} <= relative
    assert {f"stars/crop/stars_{label}.png" for label in ("night", "dawn", "day")} <= relative
    assert {f"stars/motion/stars_t{second:03d}.png" for second in (0, 5, 15)} <= relative
    assert "stars/stars_lighting_contact.png" in relative
    assert "stars/stars_motion_contact.png" in relative
    assert "metrics.json" in relative
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["scenes"][0]["scene"] == "stars"
    assert metrics["scenes"][0]["motion_changed_ratio"] > 0


def test_render_review_all_selector_and_invalid_output_parent(tmp_path: Path) -> None:
    # Given / When / Then
    assert resolve_scene_selector("all") == SCENE_KEYS
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(FileExistsError):
        render_review(ReviewRequest(("stars",), blocked, "all"))


def test_render_review_cli_rejects_unknown_scene(tmp_path: Path) -> None:
    # Given / When
    result = subprocess.run(
        [
            sys.executable,
            "tools/render_scene_review.py",
            "--scene",
            "unknown",
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_benchmark_reports_requested_measured_samples() -> None:
    # Given
    request = BenchmarkRequest(("stars",), warmups=1, measured=3)

    # When
    results = benchmark_scenes(request)

    # Then
    assert len(results) == 1
    assert results[0].scene == "stars"
    assert results[0].warmups == 1
    assert results[0].sample_count == 3
    assert results[0].median_ms <= results[0].p95_ms <= results[0].max_ms
    assert results[0].decoded_bytes >= 0
    assert results[0].rss_mib > 0
    assert DEFAULT_WARMUPS == 20
    assert DEFAULT_MEASURED == 120


def test_benchmark_cli_rejects_unknown_scene() -> None:
    # Given / When
    result = subprocess.run(
        [sys.executable, "tools/benchmark_scenes.py", "--scene", "unknown"],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then
    assert result.returncode != 0
    assert "invalid choice" in result.stderr
