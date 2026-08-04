"""Ambient-scene dispatcher with deterministic selection and lifecycle ownership."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Final, Sequence, TypedDict

import pygame

from deskbar.config import SCENE_KEYS
from deskbar.layout import Rect
from deskbar.ui import Hit, planet_horizon
from deskbar.ui.scene_aurora import AuroraRenderer
from deskbar.ui.scene_common import day_seed, hash_unit
from deskbar.ui.scene_fireflies import FirefliesRenderer
from deskbar.ui.scene_fish import FishRenderer
from deskbar.ui.scene_flow import FlowRenderer
from deskbar.ui.scene_ink import InkRenderer
from deskbar.ui.scene_ridges import RidgesRenderer
from deskbar.ui.scene_runner import RunnerRenderer
from deskbar.ui.scene_runtime import RendererHandle, SceneFrame, SceneRenderer
from deskbar.ui.scene_stars import StarsRenderer
from deskbar.ui.scene_train import TrainRenderer


AREA: Final = Rect(402, 8, 1118, 472)
FPS: Final = 20
ROTATE_S: Final = 600


class LegacySceneData(TypedDict):
    """Compatibility placeholder retained in the public scene state."""


class SceneState(TypedDict, total=False):
    """Public scene state plus the active renderer handle."""

    kind: str | None
    kind_at: float
    t_last: float | None
    data: LegacySceneData
    renderer: RendererHandle


RendererFactory = Callable[[], SceneRenderer]
_FACTORIES: Final[dict[str, RendererFactory]] = {
    "flow": FlowRenderer,
    "stars": StarsRenderer,
    "ridges": RidgesRenderer,
    "fireflies": FirefliesRenderer,
    "fish": FishRenderer,
    "aurora": AuroraRenderer,
    "train": TrainRenderer,
    "runner": RunnerRenderer,
    "ink": InkRenderer,
    "planet_horizon": planet_horizon.PlanetHorizonRenderer,
}
assert set(_FACTORIES) == set(SCENE_KEYS), "registry 必須與 config.SCENE_KEYS 同步"


def new_state() -> SceneState:
    return {"kind": None, "kind_at": -1e9, "t_last": None, "data": {}}


def _replace_renderer(state: SceneState, kind: str, now_t: float) -> RendererHandle:
    previous = state.get("renderer")
    if previous is not None:
        previous.close()
    handle = RendererHandle(_FACTORIES[kind]())
    state["kind"] = kind
    state["kind_at"] = now_t
    state["t_last"] = None
    state["data"] = {}
    state["renderer"] = handle
    return handle


def render(
    surface: pygame.Surface,
    ui: SceneState,
    now: datetime,
    t: float,
    enabled: Sequence[str] | None = None,
    weather_code: int | None = None,
) -> list[Hit]:
    """Render the selected scene and retain the existing scene-tap contract."""
    allowed = [kind for kind in (enabled if enabled else SCENE_KEYS) if kind in _FACTORIES]
    if not allowed:
        allowed = list(SCENE_KEYS)
    kind = ui["kind"]
    if kind not in allowed or t - ui["kind_at"] > ROTATE_S:
        salt = int(t) // max(1, int(ROTATE_S))
        pick = allowed[
            int(hash_unit(day_seed(now), salt, int(t * 991)) * len(allowed))
        ]
        if pick != kind or t - ui["kind_at"] > ROTATE_S:
            kind = pick
            handle = _replace_renderer(ui, kind, t)
        else:
            handle = ui.get("renderer")
    else:
        handle = ui.get("renderer")
    if kind is None:
        kind = allowed[0]
    if handle is None:
        handle = _replace_renderer(ui, kind, t)
    previous_t = ui["t_last"]
    delta = 1.0 / FPS if previous_t is None else max(0.0, min(0.25, t - previous_t))
    ui["t_last"] = t
    rect = pygame.Rect(int(AREA.x), int(AREA.y), int(AREA.w), int(AREA.h))
    panel = surface.subsurface(rect.clip(surface.get_rect()))
    handle.render(
        panel,
        SceneFrame(
            now=now,
            t=t,
            dt=delta,
            weather_code=weather_code,
            day_seed=day_seed(now),
        ),
    )
    return [Hit(Rect(AREA.x, AREA.y, AREA.w, AREA.h), "scene_tap", None)]
