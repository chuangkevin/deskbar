from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.config import SCENE_KEYS
from deskbar.ui import scenes
from deskbar.ui.scene_runtime import (
    InvalidDecodedBytesError,
    RendererClosedError,
    RendererHandle,
    SceneFrame,
)


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 8, 4, 9, 30, tzinfo=TZ)


class FakeRenderer:
    __slots__ = ("_decoded_bytes", "closed", "frame_seen", "render_count")

    def __init__(self, decoded_bytes: int = 2048) -> None:
        self._decoded_bytes = decoded_bytes
        self.closed = False
        self.frame_seen: SceneFrame | None = None
        self.render_count = 0

    @property
    def decoded_bytes(self) -> int:
        return self._decoded_bytes

    def render(self, panel: pygame.Surface, frame: SceneFrame) -> None:
        self.frame_seen = frame
        self.render_count += 1
        panel.fill((12, 34, 56))

    def close(self) -> None:
        self.closed = True


def _frame() -> SceneFrame:
    return SceneFrame(
        now=NOW,
        t=12.5,
        dt=0.1,
        weather_code=2,
        day_seed=NOW.year * 400 + NOW.timetuple().tm_yday,
    )


def test_scene_frame_is_frozen_and_carries_deterministic_inputs() -> None:
    # Given
    frame = _frame()

    # When / Then
    assert frame.now == NOW
    assert frame.t == 12.5
    assert frame.dt == 0.1
    assert frame.weather_code == 2
    assert frame.day_seed == 810616
    with pytest.raises(FrozenInstanceError):
        setattr(frame, "t", 99.0)


def test_renderer_handle_renders_reports_bytes_and_closes() -> None:
    # Given
    renderer = FakeRenderer()
    handle = RendererHandle(renderer)
    panel = pygame.Surface((16, 8))
    frame = _frame()

    # When
    handle.render(panel, frame)
    decoded_bytes = handle.decoded_bytes
    handle.close()
    handle.close()

    # Then
    assert renderer.frame_seen == frame
    assert renderer.render_count == 1
    assert decoded_bytes == 2048
    assert renderer.closed
    assert handle.decoded_bytes == 0


def test_renderer_handle_rejects_render_after_close() -> None:
    # Given
    handle = RendererHandle(FakeRenderer())
    handle.close()

    # When / Then
    with pytest.raises(RendererClosedError):
        handle.render(pygame.Surface((4, 4)), _frame())


def test_renderer_handle_rejects_negative_decoded_bytes() -> None:
    # Given
    handle = RendererHandle(FakeRenderer(decoded_bytes=-1))

    # When / Then
    with pytest.raises(InvalidDecodedBytesError):
        _ = handle.decoded_bytes


def test_scene_dispatcher_registry_matches_public_scene_keys() -> None:
    # Given / When / Then
    assert tuple(scenes._FACTORIES) == SCENE_KEYS


def test_scene_dispatcher_closes_previous_renderer_on_switch() -> None:
    # Given
    state = scenes.new_state()
    surface = pygame.Surface((1920, 480))
    scenes.render(surface, state, NOW, 10.0, enabled=["flow"])
    previous = state["renderer"]

    # When
    scenes.render(surface, state, NOW, 10.1, enabled=["stars"])

    # Then
    assert previous.closed
    assert previous.decoded_bytes == 0
    assert state["kind"] == "stars"
