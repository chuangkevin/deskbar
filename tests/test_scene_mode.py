from deskbar.ui.scene_mode import SceneModeController


def test_manual_cycle_claims_imminent_wave() -> None:
    controller = SceneModeController(auto_center_prev="notes")

    switch = controller.manual_cycle("calendar")

    assert switch.center_view == "linear"
    assert switch.reset_center_pages is True
    assert switch.persist is True
    assert switch.clear_card_overlay is True
    assert controller.auto_center_prev is None
    assert controller.auto_center_hold is True


def test_manual_cycle_order_includes_sessions() -> None:
    controller = SceneModeController()
    views = ["calendar"]
    curr = "calendar"
    for _ in range(5):
        curr = controller.manual_cycle(curr).center_view
        views.append(curr)
    assert views == ["calendar", "linear", "notes", "sessions", "scene", "calendar"]


def test_imminent_focus_switches_and_restores_previous_center() -> None:
    controller = SceneModeController()

    switch = controller.imminent_switch(
        current_center="notes",
        soon=True,
        view="dashboard",
        transition_active=False,
    )
    assert switch is not None and switch.center_view == "calendar"
    assert controller.auto_center_prev == "notes"

    restore = controller.imminent_switch(
        current_center="calendar",
        soon=False,
        view="dashboard",
        transition_active=False,
    )
    assert restore is not None and restore.center_view == "notes"
    assert controller.auto_center_prev is None
    assert controller.auto_center_hold is False


def test_imminent_hold_blocks_repeat_focus_until_wave_ends() -> None:
    controller = SceneModeController(auto_center_hold=True)

    assert controller.imminent_switch(
        current_center="linear",
        soon=True,
        view="dashboard",
        transition_active=False,
    ) is None
    assert controller.auto_center_hold is True

    assert controller.imminent_switch(
        current_center="linear",
        soon=False,
        view="dashboard",
        transition_active=False,
    ) is None
    assert controller.auto_center_hold is False

    switch = controller.imminent_switch(
        current_center="linear",
        soon=True,
        view="dashboard",
        transition_active=False,
    )
    assert switch is not None and switch.center_view == "calendar"


def test_flow_switch_is_edge_triggered() -> None:
    controller = SceneModeController()

    first = controller.flow_switch(
        current_center="calendar",
        target="scene",
        view="dashboard",
        screen_asleep=False,
    )
    assert first is not None and first.center_view == "scene"
    assert first.reset_center_pages is True

    assert controller.flow_switch(
        current_center="calendar",
        target="scene",
        view="dashboard",
        screen_asleep=False,
    ) is None

    next_target = controller.flow_switch(
        current_center="scene",
        target="calendar",
        view="dashboard",
        screen_asleep=False,
    )
    assert next_target is not None and next_target.center_view == "calendar"


def test_flow_switch_does_not_interrupt_sleep_or_imminent_takeover() -> None:
    controller = SceneModeController(auto_center_prev="notes")

    assert controller.flow_switch(
        current_center="calendar",
        target="scene",
        view="dashboard",
        screen_asleep=False,
    ) is None

    controller.auto_center_prev = None
    assert controller.flow_switch(
        current_center="calendar",
        target="scene",
        view="dashboard",
        screen_asleep=True,
    ) is None


def test_scene_tap_schedules_force_return() -> None:
    controller = SceneModeController()

    switch = controller.scene_tap("force", mono=100.0, return_after_s=60.0)

    assert switch.center_view == "calendar"
    assert controller.force_scene_at == 160.0


def test_force_switch_waits_for_grace_then_returns_to_scene() -> None:
    controller = SceneModeController(force_scene_at=160.0)

    assert controller.force_switch(
        current_center="calendar",
        view="dashboard",
        screen_asleep=False,
        mono=159.0,
    ) is None

    switch = controller.force_switch(
        current_center="calendar",
        view="dashboard",
        screen_asleep=False,
        mono=161.0,
    )
    assert switch is not None and switch.center_view == "scene"


def test_force_switch_yields_to_sleep_and_imminent_takeover() -> None:
    controller = SceneModeController(auto_center_prev="notes")

    assert controller.force_switch(
        current_center="calendar",
        view="dashboard",
        screen_asleep=False,
        mono=200.0,
    ) is None

    controller.auto_center_prev = None
    assert controller.force_switch(
        current_center="calendar",
        view="dashboard",
        screen_asleep=True,
        mono=200.0,
    ) is None
