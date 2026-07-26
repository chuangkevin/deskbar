import pygame

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import settings_view


def test_settings_actions_present():
    surf = pygame.Surface((1920, 480))
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c1"] = True
    hits = settings_view.render(surf, AppState().snapshot(), settings, None)
    actions = [h.action for h in hits]
    for a in ("rotate", "settings_done", "cycle_label", "toggle_cal", "remove_account"):
        assert a in actions
    hits2 = settings_view.render(surf, AppState().snapshot(), settings, "a@x.com")
    assert "confirm_remove" in [h.action for h in hits2]
