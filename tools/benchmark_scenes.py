"""Benchmark warmed ambient-scene frame time, decoded assets, and process RSS."""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from deskbar.config import SCENE_KEYS  # noqa: E402
from deskbar.ui import scenes  # noqa: E402


DEFAULT_WARMUPS = 20
DEFAULT_MEASURED = 120
TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class BenchmarkRequest:
    __slots__ = ("scenes", "warmups", "measured")

    scenes: tuple[str, ...]
    warmups: int
    measured: int


@dataclass(frozen=True)
class BenchmarkResult:
    __slots__ = (
        "scene",
        "warmups",
        "sample_count",
        "median_ms",
        "p95_ms",
        "max_ms",
        "decoded_bytes",
        "rss_mib",
    )

    scene: str
    warmups: int
    sample_count: int
    median_ms: float
    p95_ms: float
    max_ms: float
    decoded_bytes: int
    rss_mib: float


def _rss_mib() -> float:
    maximum = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return maximum / divisor


def _benchmark(scene: str, warmups: int, measured: int) -> BenchmarkResult:
    surface = pygame.Surface((1920, 480))
    state = scenes.new_state()
    now = datetime(2026, 8, 3, 12, 0, tzinfo=TZ)
    samples: list[float] = []
    for index in range(warmups + measured):
        started = time.perf_counter_ns()
        scenes.render(
            surface,
            state,
            now,
            index / scenes.FPS,
            enabled=(scene,),
            weather_code=1,
        )
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if index >= warmups:
            samples.append(elapsed_ms)
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    decoded_bytes = state["renderer"].decoded_bytes
    result = BenchmarkResult(
        scene=scene,
        warmups=warmups,
        sample_count=len(samples),
        median_ms=round(statistics.median(samples), 4),
        p95_ms=round(ordered[p95_index], 4),
        max_ms=round(max(samples), 4),
        decoded_bytes=decoded_bytes,
        rss_mib=round(_rss_mib(), 3),
    )
    state["renderer"].close()
    return result


def benchmark_scenes(request: BenchmarkRequest) -> tuple[BenchmarkResult, ...]:
    """Benchmark each requested scene with exact warm-up and measured counts."""
    return tuple(
        _benchmark(scene, request.warmups, request.measured)
        for scene in request.scenes
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=(*SCENE_KEYS, "all"), required=True)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--frames", type=int, default=DEFAULT_MEASURED)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    selected = SCENE_KEYS if args.scene == "all" else (args.scene,)
    pygame.init()
    results = benchmark_scenes(BenchmarkRequest(selected, args.warmups, args.frames))
    payload = {"results": [asdict(result) for result in results]}
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(encoded, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    pygame.quit()


if __name__ == "__main__":
    main()
