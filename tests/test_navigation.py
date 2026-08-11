from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from deskbar.ui.navigation import NavigationState


def test_view_switching_rejects_unknown_view():
    nav = NavigationState()
    assert nav.view == "dashboard"

    nav.set_view("settings")
    assert nav.view == "settings"

    nav.go_dashboard()
    assert nav.view == "dashboard"

    with pytest.raises(ValueError):
        nav.set_view("bogus")


def test_center_pages_clamp_flip_and_reset():
    nav = NavigationState()
    assert nav.center_page("linear") == 0
    assert nav.center_page("notes") == 0

    assert nav.set_center_page("linear", 3, total=2) == 1
    assert nav.center_page("linear") == 1

    assert nav.flip_center_page("linear", 1, total=2) == 1
    assert nav.flip_center_page("linear", -5, total=2) == 0

    nav.set_center_page("notes", 4)
    nav.reset_center_pages()
    assert nav.center_pages == {"linear": 0, "notes": 0}


def test_transition_start_sets_timer_and_clears_cache():
    pygame.init()
    nav = NavigationState()
    surf = pygame.Surface((100, 40))
    area = pygame.Rect(10, 5, 30, 20)
    nav.transition_cache = ("old",)

    nav.start_transition(surf, direction=1, area=area, now_mono=12.5)

    assert nav.transition_active() is True
    assert nav.transition_start == 12.5
    assert nav.transition_cache is None
    assert nav.transition.active() is True
    assert nav.transition_elapsed(13.0) == 0.5


def test_transition_clear_resets_timer_and_cache():
    nav = NavigationState()
    nav.transition_start = 1.0
    nav.transition_cache = ("frame",)

    nav.clear_transition()

    assert nav.transition_active() is False
    assert nav.transition_start is None
    assert nav.transition_cache is None
