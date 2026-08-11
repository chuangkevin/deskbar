from __future__ import annotations

from dataclasses import dataclass


CENTER_VIEWS = ("calendar", "linear", "notes", "sessions", "scene")
DASHBOARD_VIEW = "dashboard"
CALENDAR_VIEW = "calendar"
SCENE_VIEW = "scene"


@dataclass(frozen=True)
class CenterSwitch:
    """A requested in-memory center-view change.

    This is intentionally tiny: SceneModeController decides *whether* the center
    view should move, while App remains the adapter that mutates settings,
    starts transitions, saves preferences, and clears UI-only overlays.
    """

    center_view: str
    reset_center_pages: bool = False
    persist: bool = False
    clear_card_overlay: bool = False


@dataclass
class SceneModeController:
    """Decision module for dashboard center-view ownership.

    The dashboard has three independent reasons to change the center view:
    manual cycling, imminent-calendar focus, and scene scheduling. Keeping the
    edge-trigger and takeover memory here prevents those rules from leaking
    through App's rendering/event loop.
    """

    auto_center_prev: str | None = None
    auto_center_hold: bool = False
    flow_last_target: str | None = None
    force_scene_at: float = 0.0

    def manual_cycle(self, current_center: str) -> CenterSwitch:
        """User manually cycles the center view.

        Manual intent takes ownership of the current imminent-event wave: cancel
        any pending restore and keep calendar auto-focus from immediately
        stealing the view back.
        """

        idx = CENTER_VIEWS.index(current_center) if current_center in CENTER_VIEWS else 0
        self.auto_center_prev = None
        self.auto_center_hold = True
        return CenterSwitch(
            center_view=CENTER_VIEWS[(idx + 1) % len(CENTER_VIEWS)],
            reset_center_pages=True,
            persist=True,
            clear_card_overlay=True,
        )

    def scene_tap(
        self,
        scene_mode: str,
        mono: float,
        return_after_s: float,
    ) -> CenterSwitch:
        """Scene tap exits to calendar; force mode schedules the return."""

        if scene_mode == "force":
            self.force_scene_at = mono + return_after_s
        return CenterSwitch(center_view=CALENDAR_VIEW)

    def flow_switch(
        self,
        *,
        current_center: str,
        target: str | None,
        view: str,
        screen_asleep: bool,
    ) -> CenterSwitch | None:
        """Busy/idle scene scheduler.

        The scheduler is edge-triggered: a target can move the center once when
        it changes, but it does not keep fighting the user's manual choice
        inside the same busy/idle state.
        """

        if view != DASHBOARD_VIEW or self.auto_center_prev is not None or screen_asleep:
            return None
        if target is None or target == self.flow_last_target:
            return None
        self.flow_last_target = target
        if current_center == target:
            return None
        return CenterSwitch(center_view=target, reset_center_pages=True)

    def force_switch(
        self,
        *,
        current_center: str,
        view: str,
        screen_asleep: bool,
        mono: float,
    ) -> CenterSwitch | None:
        """Force scene mode: return to scene after the scheduled grace period."""

        if (
            view != DASHBOARD_VIEW
            or self.auto_center_prev is not None
            or screen_asleep
            or current_center == SCENE_VIEW
            or mono < self.force_scene_at
        ):
            return None
        return CenterSwitch(center_view=SCENE_VIEW)

    def imminent_switch(
        self,
        *,
        current_center: str,
        soon: bool,
        view: str,
        transition_active: bool,
    ) -> CenterSwitch | None:
        """Calendar auto-focus for imminent events.

        When an event is near, move to calendar and remember where the user was.
        Once that wave is over, restore the remembered view unless the user has
        already moved somewhere else.
        """

        if view != DASHBOARD_VIEW or transition_active:
            return None
        if not soon:
            self.auto_center_hold = False
        if (
            soon
            and not self.auto_center_hold
            and current_center != CALENDAR_VIEW
            and self.auto_center_prev is None
        ):
            self.auto_center_prev = current_center
            return CenterSwitch(center_view=CALENDAR_VIEW)
        if not soon and self.auto_center_prev is not None:
            previous = self.auto_center_prev
            self.auto_center_prev = None
            if current_center == CALENDAR_VIEW:
                return CenterSwitch(center_view=previous)
            return CenterSwitch(center_view=current_center)
        return None
