"""Tests for the weather museum ambient renderers."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pygame

from deskbar.config import SCENE_KEYS
from deskbar.ui import scenes
from deskbar.ui.scene_runtime import SceneFrame
from deskbar.ui.scene_weather_museum import (
    GlassRainRenderer,
    MagneticFogRenderer,
    ReverseLightningRenderer,
    TidalAuroraRenderer,
)

TZ = ZoneInfo("Asia/Taipei")
RENDERERS = (
    ("glass_rain", GlassRainRenderer),
    ("magnetic_fog", MagneticFogRenderer),
    ("reverse_lightning", ReverseLightningRenderer),
    ("tidal_aurora", TidalAuroraRenderer),
)


def test_registry_keys():
    for key, factory in RENDERERS:
        assert key in SCENE_KEYS
        assert key in scenes._FACTORIES
        assert scenes._FACTORIES[key] == factory


def test_renderers_deterministic_nonblack_motion():
    import numpy as np

    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    # Use t=5.8s for reverse lightning pulse window so it is active
    frame1 = SceneFrame(now=now, t=5.8, dt=0.05, weather_code=61, day_seed=2026100)

    for name, factory in RENDERERS:
        renderer = factory()

        surf1 = pygame.Surface((1118, 472))
        renderer.render(surf1, frame1)

        # 1. Non-black, contrast, and color diversity check
        arr1 = pygame.surfarray.array3d(surf1)
        assert arr1.mean() > 5.0, f"Renderer {name} output mean {arr1.mean():.2f} should not be completely black"
        assert arr1.std() > 3.0, f"Renderer {name} output std {arr1.std():.2f} should have sufficient contrast"

        sampled = arr1[::12, ::12].reshape(-1, 3)
        num_unique = len(np.unique(sampled, axis=0))
        assert num_unique >= 10, f"Renderer {name} should have diverse colors (got {num_unique})"

        # 2. Deterministic check with identical SceneFrame
        surf2 = pygame.Surface((1118, 472))
        renderer.render(surf2, frame1)
        arr2 = pygame.surfarray.array3d(surf2)
        assert (arr1 == arr2).all(), f"Same SceneFrame must produce deterministic pixel output for {name}"

        # 3. Motion check over time
        frame2 = SceneFrame(now=now, t=15.0, dt=0.05, weather_code=61, day_seed=2026100)
        surf3 = pygame.Surface((1118, 472))
        renderer.render(surf3, frame2)
        arr3 = pygame.surfarray.array3d(surf3)
        assert not (arr1 == arr3).all(), f"Pixel output should evolve smoothly over time for {name}"

        renderer.close()



def test_close_decoded_bytes():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    frame = SceneFrame(now=now, t=5.0, dt=0.05, weather_code=61, day_seed=2026100)

    for _, factory in RENDERERS:
        renderer = factory()
        surf = pygame.Surface((1118, 472))
        renderer.render(surf, frame)

        assert renderer.decoded_bytes >= 0
        renderer.close()
        assert renderer.decoded_bytes == 0


def test_switch_close():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=TZ)
    surface = pygame.Surface((1920, 480))
    ui = scenes.new_state()

    scenes.render(surface, ui, now, 0.0, enabled=["glass_rain"], weather_code=61)
    handle1 = ui.get("renderer")
    assert handle1 is not None
    assert not handle1.closed

    # Force switch to magnetic_fog by advancing t > ROTATE_S
    scenes.render(surface, ui, now, 700.0, enabled=["magnetic_fog"], weather_code=61)
    handle2 = ui.get("renderer")
    assert handle2 is not None
    assert handle2 is not handle1

    # Verify handle1 was closed upon switch
    assert handle1.closed
    assert handle1.decoded_bytes == 0
