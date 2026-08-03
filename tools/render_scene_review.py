"""Render reproducible lighting, motion, contact-sheet, and metric scene proofs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from deskbar.claudeusage import UsageInfo  # noqa: E402
from deskbar.config import SCENE_KEYS, Settings  # noqa: E402
from deskbar.store import AppState  # noqa: E402
from deskbar.ui import dashboard, scenes, theme  # noqa: E402
from deskbar.weather import Weather  # noqa: E402


TZ = ZoneInfo("Asia/Taipei")
REVIEW_TIMES = (("night", 3), ("dawn", 7), ("day", 12))
MOTION_SECONDS = (0, 5, 15)
SCENE_RECT = pygame.Rect(402, 8, 1118, 472)


@dataclass(frozen=True)
class ReviewRequest:
    __slots__ = ("scenes", "out", "mode")

    scenes: tuple[str, ...]
    out: Path
    mode: str


@dataclass(frozen=True)
class SceneMetrics:
    __slots__ = (
        "scene",
        "rgb_stddev",
        "sampled_unique_colors",
        "motion_changed_ratio",
        "lighting_changed_ratios",
    )

    scene: str
    rgb_stddev: float
    sampled_unique_colors: int
    motion_changed_ratio: float
    lighting_changed_ratios: tuple[float, float, float]


def resolve_scene_selector(selector: str) -> tuple[str, ...]:
    if selector == "all":
        return SCENE_KEYS
    if selector in SCENE_KEYS:
        return (selector,)
    raise KeyError(selector)


def _state(now: datetime) -> AppState:
    state = AppState()
    state.set_weather(Weather(
        temp=28.0,
        code=1,
        tmax=31.0,
        tmin=24.0,
        label="台北",
        fetched_at=now,
        sunrise=now.replace(hour=5, minute=25),
        sunset=now.replace(hour=18, minute=36),
    ))
    state.set_usage(UsageInfo(
        session_pct=42.0,
        session_resets_at=now + timedelta(hours=2),
        weekly_pct=58.0,
        weekly_resets_at=now + timedelta(days=3),
        fable_pct=34.0,
        fable_resets_at=now + timedelta(days=4),
        fetched_at=now,
    ))
    return state


def _dashboard_frame(scene: str, now: datetime) -> pygame.Surface:
    settings = Settings()
    settings.center_view = "scene"
    settings.scenes_enabled = (scene,)
    surface = pygame.Surface((1920, 480))
    surface.fill(theme.C["bg"])
    dashboard.render(
        surface,
        _state(now).snapshot(),
        settings,
        now,
        weather_t=50.0,
        scene_ui=scenes.new_state(),
    )
    return surface


def _motion_frames(scene: str) -> list[pygame.Surface]:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=TZ)
    state = scenes.new_state()
    rendered: list[pygame.Surface] = []
    for second in MOTION_SECONDS:
        surface = pygame.Surface((1920, 480))
        scenes.render(surface, state, now, float(second), enabled=(scene,), weather_code=1)
        rendered.append(surface.subsurface(SCENE_RECT).copy())
    handle = state.get("renderer")
    if handle is not None:
        handle.close()
    return rendered


def _contact_sheet(frames: list[pygame.Surface]) -> pygame.Surface:
    width, height = frames[0].get_size()
    sheet = pygame.Surface((width * len(frames), height), pygame.SRCALPHA)
    for index, frame in enumerate(frames):
        sheet.blit(frame, (index * width, 0))
    return sheet


def _changed_ratio(first: pygame.Surface, second: pygame.Surface) -> float:
    first_rgb = pygame.surfarray.array3d(first).astype(np.int16)
    second_rgb = pygame.surfarray.array3d(second).astype(np.int16)
    return float((np.max(np.abs(first_rgb - second_rgb), axis=2) > 12).mean())


def _metrics(
    scene: str,
    lighting: list[pygame.Surface],
    motion: list[pygame.Surface],
) -> SceneMetrics:
    day_rgb = pygame.surfarray.array3d(lighting[-1])
    sampled = day_rgb[::12, ::12].reshape(-1, 3)
    lighting_ratios = (
        _changed_ratio(lighting[0], lighting[1]),
        _changed_ratio(lighting[1], lighting[2]),
        _changed_ratio(lighting[0], lighting[2]),
    )
    return SceneMetrics(
        scene=scene,
        rgb_stddev=round(float(day_rgb.std()), 4),
        sampled_unique_colors=int(len(np.unique(sampled, axis=0))),
        motion_changed_ratio=round(_changed_ratio(motion[0], motion[-1]), 6),
        lighting_changed_ratios=tuple(round(value, 6) for value in lighting_ratios),
    )


def render_review(request: ReviewRequest) -> list[Path]:
    """Render all requested proof surfaces and return every written path."""
    request.out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    metrics: list[SceneMetrics] = []
    for scene in request.scenes:
        scene_root = request.out / scene
        dashboard_dir = scene_root / "dashboard"
        crop_dir = scene_root / "crop"
        motion_dir = scene_root / "motion"
        for directory in (dashboard_dir, crop_dir, motion_dir):
            directory.mkdir(parents=True, exist_ok=True)
        lighting_frames: list[pygame.Surface] = []
        for label, hour in REVIEW_TIMES:
            now = datetime(2026, 8, 3, hour, 0, tzinfo=TZ)
            full = _dashboard_frame(scene, now)
            crop = full.subsurface(SCENE_RECT).copy()
            lighting_frames.append(crop)
            if request.mode in ("all", "dashboard"):
                path = dashboard_dir / f"{scene}_{label}.png"
                pygame.image.save(full, path)
                written.append(path)
            if request.mode in ("all", "scene"):
                path = crop_dir / f"{scene}_{label}.png"
                pygame.image.save(crop, path)
                written.append(path)
        motion_frames = _motion_frames(scene)
        for second, frame in zip(MOTION_SECONDS, motion_frames):
            path = motion_dir / f"{scene}_t{second:03d}.png"
            pygame.image.save(frame, path)
            written.append(path)
        lighting_contact = scene_root / f"{scene}_lighting_contact.png"
        motion_contact = scene_root / f"{scene}_motion_contact.png"
        pygame.image.save(_contact_sheet(lighting_frames), lighting_contact)
        pygame.image.save(_contact_sheet(motion_frames), motion_contact)
        written.extend((lighting_contact, motion_contact))
        metrics.append(_metrics(scene, lighting_frames, motion_frames))
    metrics_path = request.out / "metrics.json"
    report = {
        "review_times": [hour for _, hour in REVIEW_TIMES],
        "motion_seconds": list(MOTION_SECONDS),
        "scenes": [asdict(scene_metrics) for scene_metrics in metrics],
    }
    metrics_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(metrics_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=(*SCENE_KEYS, "all"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("all", "dashboard", "scene"), default="all")
    args = parser.parse_args()
    pygame.init()
    request = ReviewRequest(resolve_scene_selector(args.scene), args.out, args.mode)
    for path in render_review(request):
        print(path)
    pygame.quit()


if __name__ == "__main__":
    main()
