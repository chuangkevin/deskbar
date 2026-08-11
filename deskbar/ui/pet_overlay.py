"""Render and pointer-capture controller for the global Sisi overlay."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pygame

from deskbar.ui.sisi_pet import FPS, SisiPet


class PetOverlayController:
    """Keep Sisi's animation, dirty background, and drag capture behind one seam.

    Callers decide *when* Sisi is allowed to appear (alarm/sleep policy belongs to
    ``App``), while this module owns everything necessary to draw, erase, animate,
    and drag the overlay safely on a logical pygame surface.
    """

    __slots__ = ("pet", "_background", "_dragging", "_frame_at")

    def __init__(self, settings) -> None:
        self.pet = SisiPet(settings)
        self._background: tuple[pygame.Rect, pygame.Surface] | None = None
        self._dragging = False
        self._frame_at = 0.0

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def fps(self) -> int:
        return FPS

    @staticmethod
    def _union(*rects: pygame.Rect | None) -> pygame.Rect | None:
        out = None
        for rect in rects:
            if rect is None:
                continue
            out = pygame.Rect(rect) if out is None else out.union(rect)
        return out

    def clear_background(self) -> None:
        """Forget the saved underlay after its logical canvas was redrawn."""
        self._background = None

    @contextmanager
    def preserve_background(self) -> Iterator[None]:
        """Keep the visible overlay underlay while App renders an offscreen page."""
        saved = self._background
        try:
            yield
        finally:
            self._background = saved

    def restore(self, logical: pygame.Surface | None) -> pygame.Rect | None:
        """Put back the saved underlay and return the region that changed."""
        background = self._background
        self._background = None
        if background is None or logical is None:
            return None
        rect, surface = background
        logical.blit(surface, rect.topleft)
        return rect

    def draw(self, logical: pygame.Surface | None, *, visible: bool,
             sleeping: bool = False) -> pygame.Rect | None:
        """Draw Sisi and retain the exact pixels needed to erase her next frame."""
        if not visible or logical is None:
            return None
        rect = self.pet.dirty_rect()
        if rect.w <= 0 or rect.h <= 0:
            return None
        underlay = logical.subsurface(rect).copy()
        self.pet.draw(logical, sleeping=sleeping)
        self._background = (rect, underlay)
        return rect

    def advance_if_due(self, mono: float, *, sleeping: bool = False,
                       force: bool = False) -> bool:
        """Advance the sprite at its own cadence; return whether it changed."""
        if not force and mono - self._frame_at < 1.0 / FPS:
            return False
        self.pet.advance(mono, sleeping=sleeping)
        self._frame_at = mono
        return True

    def advance_draw(self, logical: pygame.Surface | None, *, mono: float,
                     visible: bool, force: bool = False) -> pygame.Rect | None:
        """Erase the old overlay, advance it, and return one combined dirty region."""
        if not visible or logical is None:
            return None
        if not self.advance_if_due(mono, force=force):
            return None
        old_rect = self.restore(logical)
        new_rect = self.draw(logical, visible=True)
        return self._union(old_rect, new_rect)

    def draw_sleep(self, logical: pygame.Surface, *, mono: float,
                   visible: bool) -> pygame.Rect | None:
        """Draw only Sisi's sleep animation on a newly cleared black canvas."""
        self.clear_background()
        if not visible:
            return None
        self.advance_if_due(mono, sleeping=True, force=True)
        return self.draw(logical, visible=True, sleeping=True)

    def begin_drag(self, x: int, y: int, *, visible: bool) -> bool:
        """Capture a pointer only when it lands on a visible Sisi sprite."""
        if not visible or not self.pet.hit_test(x, y):
            return False
        self._dragging = True
        self.pet.begin_drag(x, y)
        return True

    def drag_to(self, x: int, y: int) -> None:
        if self._dragging:
            self.pet.drag_to(x, y)

    def finish_drag(self, x: int, y: int) -> tuple[int, int] | None:
        """Release a captured pointer and return the persistent logical position."""
        if not self._dragging:
            return None
        self.pet.drag_to(x, y)
        self._dragging = False
        return self.pet.end_drag()
