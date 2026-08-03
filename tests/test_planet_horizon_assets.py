"""行星地平線烘焙素材的尺寸、材質與 alpha 契約。"""

from pathlib import Path

import numpy as np
import pygame


ASSET_DIR = Path("deskbar/assets/scenes")
MASTER_NAMES = (
    "planet_horizon_night",
    "planet_horizon_dawn",
    "planet_horizon_day",
)
CLOUD_NAMES = ("planet_cloud_far", "planet_cloud_near")


def test_planet_horizon_baked_assets_have_production_dimensions():
    # Given: the center viewport is 1118x472 with horizontal parallax overscan
    # When: the cinematic masters and cloud layers are loaded
    # Then: every asset covers the full viewport at native runtime height
    for name in (*MASTER_NAMES, *CLOUD_NAMES):
        path = ASSET_DIR / f"{name}.png"
        assert path.exists(), f"missing baked scene asset: {path}"
        assert pygame.image.load(str(path)).get_size() == (1180, 472)


def test_planet_horizon_masters_are_opaque_and_materially_varied():
    # Given: focal lighting and planet texture must be baked rather than flat geometry
    # When: each time-of-day master is inspected
    # Then: it is fully opaque and retains substantial local tonal variation
    for name in MASTER_NAMES:
        path = ASSET_DIR / f"{name}.png"
        assert path.exists(), f"missing baked scene asset: {path}"
        surface = pygame.image.load(str(path))
        alpha = pygame.surfarray.array_alpha(surface)
        rgb = pygame.surfarray.array3d(surface)
        planet_roi = rgb[250:1000, 20:300]
        assert alpha.min() == 255
        assert float(planet_roi.std()) >= 18.0, f"{name} focal material is too flat"
        sampled = planet_roi[::12, ::12].reshape(-1, 3)
        assert len(np.unique(sampled, axis=0)) >= 180


def test_planet_horizon_cloud_layers_have_fully_transparent_borders():
    # Given: animated overlays move over bright and dark backgrounds
    # When: their alpha channels reach the source-image boundary
    # Then: no rectangular sprite edge can become visible
    for name in CLOUD_NAMES:
        path = ASSET_DIR / f"{name}.png"
        assert path.exists(), f"missing baked scene asset: {path}"
        surface = pygame.image.load(str(path))
        alpha = pygame.surfarray.array_alpha(surface)
        edges = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
        assert edges.max() == 0, f"{name} border alpha must be zero"
