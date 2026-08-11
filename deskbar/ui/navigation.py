"""Deskbar route and transition state.

This module is intentionally small: it owns navigation state and the lifecycle
of the existing slide transition, but it does not render frames. App remains
the pygame/rendering adapter; NavigationState is the deep module for route
state, page indexes, and transition bookkeeping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deskbar.ui.transitions import SlideTransition


VALID_VIEWS = frozenset({
    "dashboard",
    "settings",
    "detail",
    "alarms",
    "wifi",
    "bt",
    "screen",
    "work_sessions",
})

DEFAULT_CENTER_PAGES = ("linear", "notes")


def _default_center_pages() -> dict[str, int]:
    return {key: 0 for key in DEFAULT_CENTER_PAGES}


@dataclass
class NavigationState:
    """Owns route/page state plus SlideTransition lifecycle."""

    view: str = "dashboard"
    center_pages: dict[str, int] = field(default_factory=_default_center_pages)
    transition: SlideTransition = field(default_factory=SlideTransition)
    transition_start: float | None = None
    transition_cache: Any = None

    def __post_init__(self) -> None:
        self.set_view(self.view)
        merged = _default_center_pages()
        for key, value in self.center_pages.items():
            merged[key] = max(0, int(value))
        self.center_pages = merged

    def set_view(self, view: str) -> None:
        if view not in VALID_VIEWS:
            raise ValueError(f"unknown Deskbar view: {view!r}")
        self.view = view

    def go_dashboard(self) -> None:
        self.set_view("dashboard")

    def center_page(self, center: str) -> int:
        return max(0, int(self.center_pages.get(center, 0)))

    def set_center_page(self, center: str, page: int, total: int | None = None) -> int:
        next_page = max(0, int(page))
        if total is not None:
            next_page = min(max(0, int(total) - 1), next_page)
        self.center_pages[center] = next_page
        return next_page

    def flip_center_page(self, center: str, delta: int, total: int) -> int:
        return self.set_center_page(
            center,
            self.center_page(center) + int(delta),
            total=total,
        )

    def reset_center_pages(self) -> None:
        self.center_pages = _default_center_pages()

    def start_transition(self, logical, direction: int, area, now_mono: float) -> None:
        self.transition.start(logical, direction, area=area)
        self.transition_start = float(now_mono)
        self.transition_cache = None

    def transition_active(self) -> bool:
        return self.transition_start is not None

    def transition_elapsed(self, now_mono: float) -> float:
        if self.transition_start is None:
            return 0.0
        return float(now_mono) - self.transition_start

    def clear_transition_cache(self) -> None:
        self.transition_cache = None

    def clear_transition(self) -> None:
        self.transition_start = None
        self.transition_cache = None
