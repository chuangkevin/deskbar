"""Render full-screen morning/day/night scene proofs for human approval.

Usage:
    .venv/bin/python tools/render_scene_review.py \
        --scene planet_horizon --out .devhome/planet_horizon_review
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from deskbar.claudeusage import UsageInfo  # noqa: E402
from deskbar.config import SCENE_KEYS, Settings  # noqa: E402
from deskbar.store import AppState  # noqa: E402
from deskbar.ui import dashboard, scenes, theme  # noqa: E402
from deskbar.weather import Weather  # noqa: E402


TZ = ZoneInfo("Asia/Taipei")
REVIEW_TIMES = (("night", 3), ("morning", 7), ("day", 12))


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


def render_review(scene: str, out: Path) -> list[Path]:
    """Render the scene inside the real three-column dashboard at three times."""
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    settings.center_view = "scene"
    settings.scenes_enabled = (scene,)
    rendered: list[Path] = []
    for label, hour in REVIEW_TIMES:
        now = datetime(2026, 8, 3, hour, 0, tzinfo=TZ)
        surface = pygame.Surface((1920, 480))
        surface.fill(theme.C["bg"])
        ui = scenes.new_state()
        dashboard.render(surface, _state(now).snapshot(), settings, now,
                         weather_t=50.0, scene_ui=ui)
        path = out / f"{scene}_{label}.png"
        pygame.image.save(surface, str(path))
        rendered.append(path)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=SCENE_KEYS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pygame.init()
    for path in render_review(args.scene, args.out):
        print(path)
    pygame.quit()


if __name__ == "__main__":
    main()
