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


def test_settings_sync_interval_button_present_and_labeled():
    surf = pygame.Surface((1920, 480))
    settings = Settings()
    settings.sync_interval_min = 10
    hits = settings_view.render(surf, AppState().snapshot(), settings, None)
    matches = [h for h in hits if h.action == "cycle_sync_interval"]
    assert matches, "設定頁應該有同步頻率調整鈕"
    assert matches[0].data is None
