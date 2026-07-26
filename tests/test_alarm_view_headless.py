from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.alarms import AlarmStore
from deskbar.ui import alarm_view

NOW = datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def _draft():
    return {"hour": 7, "minute": 30, "days": set(), "label_idx": 0}


def test_alarm_view_actions_present():
    surf = pygame.Surface((1920, 480))
    hits = alarm_view.render(surf, None, _draft(), NOW)
    actions = {h.action for h in hits}
    for a in ("settings_done", "draft_hour", "draft_minute", "draft_day",
              "draft_label", "add_alarm"):
        assert a in actions


def test_alarm_view_lists_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    a1 = store.add("07:00", [0, 1, 2, 3, 4], "打卡")
    a2 = store.add("09:00", [], "吃藥")

    surf = pygame.Surface((1920, 480))
    hits = alarm_view.render(surf, store, _draft(), NOW)

    toggle_data = {h.data for h in hits if h.action == "toggle_alarm"}
    delete_data = {h.data for h in hits if h.action == "delete_alarm"}
    assert toggle_data == {a1.id, a2.id}
    assert delete_data == {a1.id, a2.id}


def test_draft_time_wraps():
    draft = {"hour": 23, "minute": 55, "days": set(), "label_idx": 0}
    alarm_view.bump_draft(draft, "hour", 1)
    assert draft["hour"] == 0

    draft["minute"] = 55
    alarm_view.bump_draft(draft, "minute", 5)
    assert draft["minute"] == 0

    draft["minute"] = 0
    alarm_view.bump_draft(draft, "minute", -5)
    assert draft["minute"] == 55
