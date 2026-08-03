"""Compatibility entry point for the split planetary-horizon baker."""

from __future__ import annotations

from pathlib import Path

from tools.scene_bakers.planet_flow import generate_planet_assets


def generate_planet_horizon_assets(out: Path) -> None:
    generate_planet_assets(out)
