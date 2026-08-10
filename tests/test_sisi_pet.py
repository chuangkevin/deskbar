from __future__ import annotations

import os
from pathlib import Path

import pygame

from deskbar.config import Settings
from deskbar.ui.sisi_pet import (
    ATLAS_COLUMNS,
    ATLAS_ROWS,
    CELL_HEIGHT,
    CELL_WIDTH,
    FRAME_COUNTS,
    PET_SIZE,
    SCREEN_H,
    SCREEN_W,
    SisiPet,
)


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

ASSET = Path("deskbar/assets/pets/sisi/spritesheet.png")


def test_sisi_pet_atlas_has_exact_v2_grid() -> None:
    atlas = pygame.image.load(str(ASSET))
    assert atlas.get_size() == (ATLAS_COLUMNS * CELL_WIDTH, ATLAS_ROWS * CELL_HEIGHT)
    assert atlas.get_flags() & pygame.SRCALPHA


def test_sisi_pet_prepares_only_valid_nontransparent_frames() -> None:
    pet = SisiPet(Settings())
    sprites = pet._sprite_frames()
    assert {name: len(frames) for name, frames in sprites.items()} == FRAME_COUNTS
    assert "failed" not in sprites
    assert all(
        pygame.surfarray.array_alpha(sprite).max() > 0
        for frames in sprites.values()
        for sprite in frames
    )
    assert pet.decoded_bytes <= 24 * 1024 * 1024
    pet.close()


def test_sisi_pet_hit_test_and_drag_clamp() -> None:
    settings = Settings(pet_x=100, pet_y=120)
    pet = SisiPet(settings)
    assert pet.hit_test(100 + PET_SIZE[0] // 2, 120 + PET_SIZE[1] // 2)
    assert not pet.hit_test(12, 12)

    pet.begin_drag(120, 140)
    pet.drag_to(-500, -500)
    assert pet.position() == (0, 0)
    pet.drag_to(9999, 9999)
    assert pet.position() == (SCREEN_W - PET_SIZE[0], SCREEN_H - PET_SIZE[1])
    assert pet.end_drag() == (SCREEN_W - PET_SIZE[0], SCREEN_H - PET_SIZE[1])
    pet.close()


def test_sisi_pet_advances_without_leaving_screen() -> None:
    pet = SisiPet(Settings(pet_x=4, pet_y=300))
    pet.state.direction = -1
    for i in range(80):
        pet.advance(i / 8)
        rect = pet.rect()
        assert 0 <= rect.x <= SCREEN_W - PET_SIZE[0]
        assert 0 <= rect.y <= SCREEN_H - PET_SIZE[1]
    pet.close()
