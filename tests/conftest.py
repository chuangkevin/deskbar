import os

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


@pytest.fixture(scope="session", autouse=True)
def _pygame_session():
    pygame.init()
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def _isolate_usage_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKBAR_USAGE_CACHE", str(tmp_path / "usage_cache.json"))
