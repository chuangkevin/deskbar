"""Global draggable overlay pet for 喜喜 (Sisi)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pygame

from deskbar import config
from deskbar.ui.scene_assets import SceneAssets
from deskbar.ui.scene_common import hash_unit


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "pets" / "sisi"
SCREEN_W: Final = 1920
SCREEN_H: Final = 480
ATLAS_COLUMNS: Final = 8
ATLAS_ROWS: Final = 11
CELL_WIDTH: Final = 192
CELL_HEIGHT: Final = 208
PET_SIZE: Final = (144, 156)
FPS: Final = 8
TOUCH_PAD: Final = 22

ANIMATION_ROWS: Final = {
    "idle": 0,
    "run_right": 1,
    "run_left": 2,
    "greeting": 3,
    "hop": 4,
    "sleeping": 5,
    "waiting": 6,
    "grooming": 7,
    "looking": 8,
}
FRAME_COUNTS: Final = {
    "idle": 7,
    "run_right": 8,
    "run_left": 8,
    "greeting": 4,
    "hop": 5,
    "sleeping": 8,
    "waiting": 6,
    "grooming": 6,
    "looking": 6,
}
FRAME_COLUMNS: Final = {
    # Kevin 指定小喜喜喜歡趴著睡，但坐著打瞌睡也可以留著。
    # 因此夜間睡眠以趴臥/蜷睡為主，穿插坐著閉眼打瞌睡。
    "sleeping": (7, 2, 7, 2, 0, 1, 7, 2),
}
FRAME_RATES: Final = {
    "idle": 3.5,
    "run_right": 9.0,
    "run_left": 9.0,
    "greeting": 4.0,
    "hop": 7.0,
    "sleeping": 0.35,
    "waiting": 3.0,
    "grooming": 5.5,
    "looking": 3.5,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class SisiPetState:
    x: float = config.DEFAULT_PET_X
    y: float = config.DEFAULT_PET_Y
    direction: int = -1
    activity: str = "wander"
    activity_elapsed: float = 0.0
    activity_duration: float = 7.0
    animation_elapsed: float = 0.0
    sleep_animation_elapsed: float = 0.0
    activity_index: int = 0
    last_t: float | None = None
    drag_dx: float = 0.0
    drag_dy: float = 0.0
    dragging: bool = False


class SisiPet:
    """A tiny always-on-top pet with its own movement and drag state."""

    __slots__ = ("_assets", "_frames", "_state")

    def __init__(self, settings=None) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._frames: dict[str, tuple[pygame.Surface, ...]] | None = None
        self._state = SisiPetState()
        if settings is not None:
            self.load_position(settings)

    @property
    def state(self) -> SisiPetState:
        return self._state

    @property
    def decoded_bytes(self) -> int:
        cached_frames = () if self._frames is None else self._frames.values()
        frame_surfaces = {
            id(surface): surface
            for frames in cached_frames
            for surface in frames
        }
        return self._assets.decoded_bytes + sum(
            surface.get_width() * surface.get_height() * 4
            for surface in frame_surfaces.values()
        )

    def load_position(self, settings) -> None:
        max_x = SCREEN_W - PET_SIZE[0]
        max_y = SCREEN_H - PET_SIZE[1]
        self._state.x = _clamp(float(getattr(settings, "pet_x", config.DEFAULT_PET_X)), 0, max_x)
        self._state.y = _clamp(float(getattr(settings, "pet_y", config.DEFAULT_PET_Y)), 0, max_y)

    def position(self) -> tuple[int, int]:
        return round(self._state.x), round(self._state.y)

    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self._state.x), round(self._state.y), *PET_SIZE)

    def dirty_rect(self) -> pygame.Rect:
        return self.rect().clip(pygame.Rect(0, 0, SCREEN_W, SCREEN_H))

    def _sprite_frames(self) -> dict[str, tuple[pygame.Surface, ...]]:
        if self._frames is not None:
            return self._frames
        atlas = self._assets.load("spritesheet")
        expected_size = (ATLAS_COLUMNS * CELL_WIDTH, ATLAS_ROWS * CELL_HEIGHT)
        if atlas.get_size() != expected_size:
            raise ValueError(
                f"Sisi atlas must be {expected_size}, got {atlas.get_size()}"
            )
        frames: dict[str, tuple[pygame.Surface, ...]] = {}
        for name, row in ANIMATION_ROWS.items():
            columns = FRAME_COLUMNS.get(name, range(FRAME_COUNTS[name]))
            frames[name] = tuple(
                pygame.transform.smoothscale(
                    atlas.subsurface(
                        pygame.Rect(column * CELL_WIDTH, row * CELL_HEIGHT,
                                    CELL_WIDTH, CELL_HEIGHT)
                    ),
                    PET_SIZE,
                )
                for column in columns
            )
        self._frames = frames
        return frames

    def _choose_next_activity(self) -> None:
        state = self._state
        state.activity_index += 1
        unit = hash_unit(state.activity_index, 20260810)
        choices = ("wander", "wander", "idle", "looking", "grooming", "greeting", "hop")
        state.activity = choices[min(len(choices) - 1, int(unit * len(choices)))]
        state.activity_duration = 3.0 + hash_unit(state.activity_index, 20260811) * 9.0
        state.activity_elapsed = 0.0
        if hash_unit(state.activity_index, 20260812) > 0.76:
            state.direction *= -1

    def _animation_name(self) -> str:
        state = self._state
        if state.dragging:
            return "run_right" if state.direction >= 0 else "run_left"
        if state.activity == "wander":
            return "run_right" if state.direction >= 0 else "run_left"
        return {
            "idle": "idle",
            "looking": "looking",
            "grooming": "grooming",
            "greeting": "greeting",
            "hop": "hop",
            "waiting": "waiting",
        }.get(state.activity, "idle")

    def current_sprite(self, sleeping: bool = False) -> pygame.Surface:
        animation = "sleeping" if sleeping else self._animation_name()
        frames = self._sprite_frames()[animation]
        elapsed = self._state.sleep_animation_elapsed if sleeping \
            else self._state.animation_elapsed
        index = int(elapsed * FRAME_RATES[animation]) % len(frames)
        return frames[index]

    def advance(self, mono: float, sleeping: bool = False) -> None:
        state = self._state
        if state.last_t is None:
            state.last_t = mono
            return
        dt = max(0.0, min(0.25, mono - state.last_t))
        state.last_t = mono
        if sleeping:
            state.sleep_animation_elapsed += dt
            return
        state.animation_elapsed += dt
        if state.dragging:
            return

        remaining = dt
        max_x = SCREEN_W - PET_SIZE[0]
        while remaining > 0.0:
            step = min(remaining, 1.0 / 60.0)
            state.activity_elapsed += step
            if state.activity == "wander":
                speed = 44.0 + hash_unit(state.activity_index, 20260813) * 28.0
                state.x += state.direction * speed * step
                if state.x <= 0:
                    state.x = 0
                    state.direction = 1
                elif state.x >= max_x:
                    state.x = max_x
                    state.direction = -1
            if state.activity_elapsed >= state.activity_duration:
                self._choose_next_activity()
            remaining -= step

    def begin_drag(self, x: int, y: int) -> None:
        state = self._state
        state.dragging = True
        state.drag_dx = x - state.x
        state.drag_dy = y - state.y
        state.activity = "wander"
        state.activity_elapsed = 0.0

    def drag_to(self, x: int, y: int) -> None:
        state = self._state
        old_x = state.x
        max_x = SCREEN_W - PET_SIZE[0]
        max_y = SCREEN_H - PET_SIZE[1]
        state.x = _clamp(float(x) - state.drag_dx, 0, max_x)
        state.y = _clamp(float(y) - state.drag_dy, 0, max_y)
        if abs(state.x - old_x) >= 1:
            state.direction = 1 if state.x >= old_x else -1

    def end_drag(self) -> tuple[int, int]:
        self._state.dragging = False
        self._state.activity = "idle"
        self._state.activity_elapsed = 0.0
        return self.position()

    def hit_test(self, x: int, y: int) -> bool:
        rect = self.rect()
        if not rect.inflate(TOUCH_PAD * 2, TOUCH_PAD * 2).collidepoint(x, y):
            return False
        if rect.collidepoint(x, y):
            sprite = self.current_sprite()
            sx = int(_clamp(x - rect.x, 0, PET_SIZE[0] - 1))
            sy = int(_clamp(y - rect.y, 0, PET_SIZE[1] - 1))
            if sprite.get_at((sx, sy)).a > 18:
                return True
        body = rect.inflate(-round(PET_SIZE[0] * 0.25), -round(PET_SIZE[1] * 0.25))
        return body.collidepoint(x, y)

    def draw(self, surface: pygame.Surface, sleeping: bool = False) -> pygame.Rect:
        rect = self.rect()
        surface.blit(self.current_sprite(sleeping=sleeping), rect.topleft)
        return rect

    def close(self) -> None:
        self._frames = None
        self._assets.close()
