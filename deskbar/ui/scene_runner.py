"""Self-playing 8-bit platform level with real movement and collision rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pygame

from deskbar.ui.scene_assets import SceneAssets
from deskbar.ui.scene_runtime import SceneFrame


ASSET_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "scenes"
BASE_X: Final = -(1240 - 1118) // 2
PANEL_WIDTH: Final = 1118
PANEL_HEIGHT: Final = 472
SKY: Final = (92, 148, 252)
GROUND_Y: Final = 380
PLAYER_WIDTH: Final = 48
PLAYER_HEIGHT: Final = 68
RUN_SPEED: Final = 135.0
ENEMY_SPEED: Final = 34.0
GRAVITY: Final = 900.0
JUMP_SPEED: Final = -550.0
FINISH_X: Final = 4700
LEVEL_LENGTH: Final = 5120

PIPES: Final = (
    (620, 64),
    (1380, 80),
    (2560, 64),
    (3910, 80),
)
BLOCKS: Final = (
    (960, 260, "brick"),
    (992, 260, "question"),
    (1024, 260, "brick"),
    (2180, 228, "brick"),
    (2212, 228, "question"),
    (2244, 228, "brick"),
    (3040, 260, "brick"),
    (3072, 260, "question"),
    (3104, 260, "brick"),
    (4260, 244, "brick"),
    (4292, 244, "question"),
    (4324, 244, "brick"),
)
GAPS: Final = ((1840, 1960), (3370, 3490))
ENEMY_SPAWNS: Final = (1130, 1700, 2310, 2860, 3650, 4310)


@dataclass
class EnemyState:
    x: float
    direction: int = -1
    alive: bool = True


def _new_enemies() -> list[EnemyState]:
    return [EnemyState(float(x)) for x in ENEMY_SPAWNS]


@dataclass
class RunnerState:
    x: float = 120.0
    y: float = GROUND_Y - PLAYER_HEIGHT
    vx: float = RUN_SPEED
    vy: float = 0.0
    on_ground: bool = True
    phase: str = "running"
    phase_timer: float = 0.0
    elapsed: float = 0.0
    deaths: int = 0
    finishes: int = 0
    used_blocks: set[int] = field(default_factory=set)
    enemies: list[EnemyState] = field(default_factory=_new_enemies)


def _player_rect(state: RunnerState) -> pygame.Rect:
    return pygame.Rect(round(state.x), round(state.y), PLAYER_WIDTH, PLAYER_HEIGHT)


def _ground_at(x: float) -> bool:
    return not any(start <= x <= end for start, end in GAPS)


def _solid_specs() -> tuple[tuple[pygame.Rect, str, int], ...]:
    pipes = tuple(
        (pygame.Rect(x, GROUND_Y - height, 56, height), "pipe", index)
        for index, (x, height) in enumerate(PIPES)
    )
    blocks = tuple(
        (pygame.Rect(x, y, 32, 32), "block", index)
        for index, (x, y, _kind) in enumerate(BLOCKS)
    )
    return pipes + blocks


SOLIDS: Final = _solid_specs()


def _reset(state: RunnerState) -> None:
    state.x = 120.0
    state.y = GROUND_Y - PLAYER_HEIGHT
    state.vx = RUN_SPEED
    state.vy = 0.0
    state.on_ground = True
    state.phase = "running"
    state.phase_timer = 0.0
    state.used_blocks.clear()
    state.enemies = _new_enemies()


def _kill(state: RunnerState) -> None:
    if state.phase != "running":
        return
    state.phase = "dead"
    state.phase_timer = 1.65
    state.vx = 0.0
    state.vy = -360.0
    state.deaths += 1


def _nearest_hazard(state: RunnerState) -> tuple[float, str] | None:
    right = state.x + PLAYER_WIDTH
    candidates = [(float(x), "pipe") for x, _height in PIPES if x + 56 >= right]
    candidates.extend((float(start), "gap") for start, _end in GAPS if start >= right - 4)
    candidates.extend(
        (enemy.x, "enemy")
        for enemy in state.enemies
        if enemy.alive and enemy.x + 32 >= right
    )
    return min(candidates, default=None)


def _advance_enemy(enemy: EnemyState, dt: float) -> None:
    previous = enemy.x
    enemy.x += enemy.direction * ENEMY_SPEED * dt
    rect = pygame.Rect(round(enemy.x), GROUND_Y - 32, 32, 32)
    pipe_rects = (spec[0] for spec in SOLIDS if spec[1] == "pipe")
    if any(rect.colliderect(pipe) for pipe in pipe_rects) or not _ground_at(enemy.x + 16):
        enemy.x = previous
        enemy.direction *= -1


def _step_running(state: RunnerState, dt: float, auto_jump: bool) -> None:
    if auto_jump and state.on_ground:
        hazard = _nearest_hazard(state)
        if hazard is not None:
            hazard_x, kind = hazard
            jump_distance = {"pipe": 55.0, "enemy": 75.0, "gap": 12.0}[kind]
            if -3.0 <= hazard_x - (state.x + PLAYER_WIDTH) <= jump_distance:
                state.vy = JUMP_SPEED
                state.on_ground = False

    state.vx = RUN_SPEED
    previous = _player_rect(state)
    state.x += state.vx * dt
    moved = _player_rect(state)
    for solid, _kind, _index in SOLIDS:
        if moved.colliderect(solid) and previous.bottom > solid.top + 2 \
                and previous.top < solid.bottom - 2:
            state.x = solid.left - PLAYER_WIDTH
            state.vx = 0.0
            moved = _player_rect(state)

    previous = moved
    state.vy += GRAVITY * dt
    state.y += state.vy * dt
    moved = _player_rect(state)
    state.on_ground = False
    for solid, kind, index in SOLIDS:
        if not moved.colliderect(solid):
            continue
        if state.vy >= 0.0 and previous.bottom <= solid.top + 2:
            state.y = solid.top - PLAYER_HEIGHT
            state.vy = 0.0
            state.on_ground = True
        elif state.vy < 0.0 and previous.top >= solid.bottom - 2:
            state.y = solid.bottom
            state.vy = 0.0
            if kind == "block":
                state.used_blocks.add(index)
        moved = _player_rect(state)

    if state.vy >= 0.0 and previous.bottom <= GROUND_Y <= moved.bottom \
            and _ground_at(state.x + PLAYER_WIDTH / 2):
        state.y = GROUND_Y - PLAYER_HEIGHT
        state.vy = 0.0
        state.on_ground = True
        moved = _player_rect(state)

    for enemy in state.enemies:
        if enemy.alive:
            _advance_enemy(enemy, dt)
    for enemy in state.enemies:
        if not enemy.alive:
            continue
        enemy_rect = pygame.Rect(round(enemy.x), GROUND_Y - 32, 32, 32)
        if not moved.colliderect(enemy_rect):
            continue
        if state.vy > 60.0 and previous.bottom <= enemy_rect.top + 10:
            enemy.alive = False
            state.y = enemy_rect.top - PLAYER_HEIGHT
            state.vy = -270.0
        else:
            _kill(state)
        break

    if state.y > PANEL_HEIGHT + 72:
        _kill(state)
    elif state.x + PLAYER_WIDTH >= FINISH_X:
        state.phase = "won"
        state.phase_timer = 2.4
        state.vx = 0.0
        state.finishes += 1


def advance_runner(state: RunnerState, dt: float, auto_jump: bool = True) -> None:
    """Advance runner rules with fixed substeps so collisions cannot tunnel."""
    remaining = max(0.0, min(dt, 0.25))
    while remaining > 0.0:
        step = min(remaining, 1.0 / 120.0)
        state.elapsed += step
        if state.phase == "dead":
            state.vy += GRAVITY * step
            state.y += state.vy * step
            state.phase_timer -= step
            if state.phase_timer <= 0.0:
                _reset(state)
        elif state.phase == "won":
            state.phase_timer -= step
            if state.phase_timer <= 0.0:
                _reset(state)
        else:
            _step_running(state, step, auto_jump)
        remaining -= step


def _blit_repeated(panel: pygame.Surface, layer: pygame.Surface, offset: float) -> None:
    width = layer.get_width()
    left = BASE_X - round(offset) % width
    while left > 0:
        left -= width
    while left < panel.get_width():
        panel.blit(layer, (left, 0))
        left += width


class RunnerRenderer:
    __slots__ = ("_assets", "_frames", "_sprites", "_state")

    def __init__(self) -> None:
        self._assets = SceneAssets(ASSET_DIR)
        self._frames: tuple[pygame.Surface, pygame.Surface] | None = None
        self._sprites: dict[str, pygame.Surface] | None = None
        self._state = RunnerState()

    @property
    def decoded_bytes(self) -> int:
        return self._assets.decoded_bytes

    @property
    def physics_state(self) -> RunnerState:
        return self._state

    def _runner_frames(self) -> tuple[pygame.Surface, pygame.Surface]:
        if self._frames is None:
            sheet = self._assets.load("runner_sprite_sheet")
            self._frames = (
                sheet.subsurface(pygame.Rect(564, 212, 64, 72)),
                sheet.subsurface(pygame.Rect(644, 212, 64, 72)),
            )
        return self._frames

    def _world_sprites(self) -> dict[str, pygame.Surface]:
        if self._sprites is None:
            atlas = self._assets.load("runner_obstacles")
            self._sprites = {
                "pipe_short": atlas.subsurface(pygame.Rect(210, 316, 56, 64)),
                "pipe_tall": atlas.subsurface(pygame.Rect(648, 300, 56, 80)),
                "goomba": atlas.subsurface(pygame.Rect(368, 348, 32, 32)),
                "brick": atlas.subsurface(pygame.Rect(470, 284, 32, 32)),
                "question": atlas.subsurface(pygame.Rect(502, 284, 32, 32)),
            }
        return self._sprites

    def _camera_x(self) -> float:
        return max(0.0, min(self._state.x - 180.0, LEVEL_LENGTH - PANEL_WIDTH))

    @staticmethod
    def _draw_finish(panel: pygame.Surface, camera: float) -> None:
        pole_x = round(FINISH_X - camera)
        pygame.draw.rect(panel, (248, 248, 248), (pole_x, 126, 4, GROUND_Y - 126))
        pygame.draw.rect(panel, (48, 32, 24), (pole_x - 2, 122, 8, 8))
        pygame.draw.polygon(panel, (0, 184, 48),
                            ((pole_x - 34, 138), (pole_x, 138), (pole_x, 166)))
        castle_x = round(FINISH_X + 170 - camera)
        pygame.draw.rect(panel, (48, 24, 16), (castle_x, 284, 176, 96))
        pygame.draw.rect(panel, (232, 80, 24), (castle_x + 8, 292, 160, 88))
        for tower_x in (castle_x, castle_x + 64, castle_x + 128):
            pygame.draw.rect(panel, (48, 24, 16), (tower_x, 252, 48, 40))
            pygame.draw.rect(panel, (232, 80, 24), (tower_x + 8, 260, 32, 32))
        pygame.draw.rect(panel, (48, 24, 16), (castle_x + 72, 332, 32, 48))

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        advance_runner(self._state, frame.dt)
        camera = self._camera_x()
        panel.blit(self._assets.load("runner_base_day"), (BASE_X, 0))
        _blit_repeated(panel, self._assets.load("runner_far"), camera * 0.10)
        _blit_repeated(panel, self._assets.load("runner_mid"), camera * 0.28)
        _blit_repeated(panel, self._assets.load("runner_near"), camera)

        for start, end in GAPS:
            left = round(start - camera)
            right = round(end - camera)
            if right > 0 and left < PANEL_WIDTH:
                panel.fill(SKY, pygame.Rect(left, GROUND_Y, right - left, PANEL_HEIGHT - GROUND_Y))

        sprites = self._world_sprites()
        for x, height in PIPES:
            screen_x = round(x - camera)
            if -56 < screen_x < PANEL_WIDTH:
                pipe = sprites["pipe_tall" if height == 80 else "pipe_short"]
                panel.blit(pipe, (screen_x, GROUND_Y - height))
        for index, (x, y, kind) in enumerate(BLOCKS):
            screen_x = round(x - camera)
            if -32 < screen_x < PANEL_WIDTH:
                sprite = sprites["brick" if index in self._state.used_blocks else kind]
                panel.blit(sprite, (screen_x, y))
        for enemy in self._state.enemies:
            screen_x = round(enemy.x - camera)
            if enemy.alive and -32 < screen_x < PANEL_WIDTH:
                panel.blit(sprites["goomba"], (screen_x, GROUND_Y - 32))

        self._draw_finish(panel, camera)
        runner = self._runner_frames()[int(self._state.elapsed * 8.0) % 2]
        runner_x = round(self._state.x - camera - 8)
        panel.blit(runner, (runner_x, round(self._state.y)))

    def close(self) -> None:
        self._frames = None
        self._sprites = None
        self._assets.close()
