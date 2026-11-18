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


@pytest.fixture(autouse=True)
def _restore_usage_width_layout():
    """dashboard.render 會依內容自動調右欄寬度（改版面全域值）；每個測試結束還原預設，
    免得影響後面依預設版面（右欄 600）斷言的測試。"""
    yield
    from deskbar import config
    from deskbar.ui import dashboard
    dashboard.apply_usage_width(config.DEFAULT_USAGE_WIDTH)
