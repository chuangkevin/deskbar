from datetime import datetime, timedelta, timezone

import pygame

from deskbar.config import Settings
from deskbar.store import Snapshot
from deskbar.ui import dashboard, worksessionwidget
from deskbar.work_sessions import WorkSessionItem, WorkSessionSnapshot

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _snap(count=1, minutes=1):
    items = tuple(
        WorkSessionItem("codex" if index % 2 == 0 else "claude", f"project-{index}",
                        NOW - timedelta(minutes=minutes), f"opaque-open-id-{index:012d}")
        for index in range(count)
    )
    return Snapshot([], None, {}, 0, work_sessions=WorkSessionSnapshot(items))


def test_summary_disappears_for_no_active_items():
    surface = pygame.Surface((1920, 480))
    hits, height = worksessionwidget.render_summary(surface, _snap(minutes=30), NOW, 1540, 362, 360)
    assert hits == []
    assert height == 0


def test_full_view_has_bounded_touch_hits_and_honest_app_copy(monkeypatch):
    surface = pygame.Surface((1280, 720))
    texts = []
    original = worksessionwidget._text

    def spy(*args, **kwargs):
        texts.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(worksessionwidget, "_text", spy)
    hits = worksessionwidget.render_full_view(surface, _snap(count=18), NOW)
    action_hits = [hit for hit in hits if hit.action == "enqueue_work_session_action"]
    assert len(action_hits) == 6
    assert any(text.startswith("開啟 ") for text in texts)
    assert not any("此對話" in text for text in texts)
    for hit in hits:
        assert 0 <= hit.rect.x <= surface.get_width()
        assert 0 <= hit.rect.y <= surface.get_height()
        assert hit.rect.x + hit.rect.w <= surface.get_width()
        assert hit.rect.y + hit.rect.h <= surface.get_height()


def test_dashboard_summary_stays_visible_on_480px_panel_with_todos():
    surface = pygame.Surface((1920, 480))
    snap = Snapshot([], None, {}, 0, linear=[object()], work_sessions=_snap(count=4).work_sessions)
    hits = []
    dashboard._render_right_work_sessions(surface, snap, NOW, hits)
    assert hits
    assert all(hit.rect.y + hit.rect.h <= surface.get_height() for hit in hits)


def test_dashboard_sessions_are_available_from_notes_center_view():
    surface = pygame.Surface((1920, 480))
    settings = Settings()
    settings.center_view = "notes"

    class EmptyNotes:
        def list(self):
            return []

    hits = dashboard.render(surface, _snap(count=6), settings, NOW,
                            notes_store=EmptyNotes())
    assert any(hit.action == "open_work_sessions" for hit in hits)
