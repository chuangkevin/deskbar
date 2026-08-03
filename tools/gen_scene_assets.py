"""Deterministically generate every production ambient-scene PNG."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from tools.scene_bakers.fish_ink import generate_fish_ink_assets  # noqa: E402
from tools.scene_bakers.planet_flow import generate_planet_flow_assets  # noqa: E402
from tools.scene_bakers.ridges_fireflies import generate_ridges_fireflies_assets  # noqa: E402
from tools.scene_bakers.stars_aurora import generate_stars_aurora_assets  # noqa: E402
from tools.scene_bakers.train_runner import generate_train_runner_assets  # noqa: E402
from tools.scene_bakers.weather_support import generate_weather_support_assets  # noqa: E402


DEFAULT_OUT = Path(__file__).resolve().parent.parent / "deskbar" / "assets" / "scenes"


def expected_asset_names() -> tuple[str, ...]:
    names: list[str] = ["cumulus_0.png", "cumulus_1.png", "sun_ball.png"]
    for scene in ("flow", "stars", "ridges", "fireflies", "fish", "aurora",
                  "train", "runner", "ink"):
        names.extend(f"{scene}_base_{light}.png" for light in ("night", "dawn", "day"))
    names.extend(f"planet_{layer}_{light}.png" for layer in ("sky", "body", "rim")
                 for light in ("night", "dawn", "day"))
    names.extend((
        "planet_cloud_far.png", "planet_cloud_near.png", "planet_haze.png",
        "flow_filament_veil.png", "flow_brush_0.png", "flow_brush_1.png",
        "stars_dust_far.png", "stars_dust_near.png", "stars_sprite_0.png",
        "stars_sprite_1.png", "stars_sprite_2.png", "stars_meteor.png",
        "aurora_curtain_0.png", "aurora_curtain_1.png", "aurora_curtain_2.png",
        "ridges_far.png", "ridges_mid.png", "ridges_near.png", "ridges_fog.png",
        "ridges_shadow.png", "fireflies_grass_far.png", "fireflies_grass_near.png",
        "fireflies_haze.png", "fireflies_glow_0.png", "fireflies_glow_1.png",
        "fish_sprite_0.png", "fish_sprite_1.png", "fish_sprite_2.png",
        "fish_wake_0.png", "fish_wake_1.png", "ink_bloom_0.png",
        "ink_bloom_1.png", "ink_bloom_2.png", "train_far.png", "train_mid.png",
        "train_near.png", "train_window_reflection.png", "runner_far.png",
        "runner_mid.png", "runner_near.png", "runner_sprite_sheet.png",
        "runner_obstacles.png",
    ))
    return tuple(sorted(names))


def generate_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    generate_weather_support_assets(out)
    generate_planet_flow_assets(out)
    generate_stars_aurora_assets(out)
    generate_ridges_fireflies_assets(out)
    generate_fish_ink_assets(out)
    generate_train_runner_assets(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    pygame.init()
    generate_all(args.out)
    pygame.quit()


if __name__ == "__main__":
    main()
