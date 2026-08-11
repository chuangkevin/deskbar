from __future__ import annotations

import os

import pygame

from deskbar.config import Settings
from deskbar.ui.pet_overlay import PetOverlayController
from deskbar.ui.sisi_pet import PET_SIZE, SCREEN_H, SCREEN_W


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()


def test_overlay_draw_restore_round_trip_and_offscreen_preservation() -> None:
    logical = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    logical.fill((16, 34, 52, 255))
    overlay = PetOverlayController(Settings(pet_x=100, pet_y=120))
    before = pygame.image.tobytes(logical, "RGBA")

    rect = overlay.draw(logical, visible=True)
    assert rect == overlay.pet.rect()
    assert pygame.image.tobytes(logical, "RGBA") != before

    with overlay.preserve_background():
        overlay.clear_background()
        assert overlay.restore(logical) is None

    assert overlay.restore(logical) == rect
    assert pygame.image.tobytes(logical, "RGBA") == before


def test_overlay_tick_throttles_then_returns_one_dirty_region() -> None:
    logical = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay = PetOverlayController(Settings(pet_x=100, pet_y=120))
    overlay.draw(logical, visible=True)

    dirty = overlay.advance_draw(logical, mono=10.0, visible=True)
    assert dirty is not None and dirty.contains(overlay.pet.rect())
    assert overlay.advance_draw(logical, mono=10.01, visible=True) is None


def test_overlay_drag_capture_respects_visibility_and_persists_clamped_position() -> None:
    overlay = PetOverlayController(Settings(pet_x=100, pet_y=120))
    assert overlay.begin_drag(120, 140, visible=False) is False
    assert overlay.begin_drag(120, 140, visible=True) is True
    assert overlay.dragging is True

    overlay.drag_to(9999, 9999)
    assert overlay.finish_drag(9999, 9999) == (SCREEN_W - PET_SIZE[0], SCREEN_H - PET_SIZE[1])
    assert overlay.dragging is False
