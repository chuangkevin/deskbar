from datetime import datetime, timedelta, timezone

import pygame

from deskbar.config import Settings
from deskbar.store import Snapshot
from deskbar.ui import dashboard, theme, worksessionwidget
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


def test_render_center_view_displays_up_to_six_cards_within_tl_area_and_bounds():
    from deskbar.layout import Rect
    surface = pygame.Surface((1920, 480))
    tl_area = Rect(420, 52, 1100, 368)
    settings = Settings()

    snap = _snap(count=10)
    hits = worksessionwidget.render_center_view(surface, snap, settings, tl_area, NOW)

    card_hits = [hit for hit in hits if hit.action == "enqueue_work_session_action"]
    assert len(card_hits) == 6
    for hit in hits:
        assert hit.action in {"enqueue_work_session_action", "enqueue_claude_dispatch"}
        assert tl_area.x <= hit.rect.x <= tl_area.x + tl_area.w
        assert tl_area.y <= hit.rect.y <= tl_area.y + tl_area.h
        assert hit.rect.x + hit.rect.w <= tl_area.x + tl_area.w
        assert hit.rect.y + hit.rect.h <= tl_area.y + tl_area.h


def test_render_center_view_empty_state_for_zero_items():
    from deskbar.layout import Rect
    surface = pygame.Surface((1920, 480))
    tl_area = Rect(420, 52, 1100, 368)
    settings = Settings()

    snap = _snap(count=0)
    hits = worksessionwidget.render_center_view(surface, snap, settings, tl_area, NOW)

    assert [hit.action for hit in hits] == ["enqueue_claude_dispatch"]


def test_render_center_view_shows_unread_badge_and_honest_labels(monkeypatch):
    from deskbar.layout import Rect
    surface = pygame.Surface((1920, 480))
    tl_area = Rect(420, 52, 1100, 368)
    settings = Settings()
    texts = []
    original = worksessionwidget._text

    def spy(*args, **kwargs):
        texts.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(worksessionwidget, "_text", spy)

    item1 = WorkSessionItem("codex", "project-0", NOW - timedelta(minutes=1), "opaque-open-id-000000000000", activity_state="result")
    item2 = WorkSessionItem("claude", "project-1", NOW - timedelta(minutes=2), "opaque-open-id-000000000001", activity_state="working")
    snapshot = WorkSessionSnapshot((item1, item2), unseen_keys=frozenset({
        ("codex", "opaque-open-id-000000000000"),
        ("claude", "opaque-open-id-000000000001"),
    }))
    snap = Snapshot([], None, {}, 0, work_sessions=snapshot)

    hits = worksessionwidget.render_center_view(surface, snap, settings, tl_area, NOW)
    assert len(hits) == 3
    assert any("結果待看" in text for text in texts)
    assert any("有新進度" in text for text in texts)
    assert "✓ 結果待看" in texts
    assert any(text.startswith("▶ 執行中") for text in texts)
    assert not any("此對話" in t for t in texts)
    assert not any("%" in t for t in texts)
    assert "Claude Dispatch ↗" in texts
    dispatch = next(hit for hit in hits if hit.action == "enqueue_claude_dispatch")
    assert (dispatch.rect.w, dispatch.rect.h) == (232, 46)


def test_workbench_source_identity_colors_are_codex_sky_blue_and_claude_orange():
    codex_bg, _ = worksessionwidget._source_chip_colors("codex")
    claude_bg, _ = worksessionwidget._source_chip_colors("claude")
    assert codex_bg == theme.C["work_codex"]
    assert claude_bg == theme.C["work_claude"]
    assert codex_bg != claude_bg


def test_center_workbench_keeps_a_middle_lane_for_sisi_and_six_click_targets():
    from deskbar.layout import Rect

    surface = pygame.Surface((1920, 480))
    tl_area = Rect(420, 52, 1100, 368)
    hits = worksessionwidget.render_center_view(surface, _snap(count=6), Settings(), tl_area, NOW)

    card_hits = [hit for hit in hits if hit.action == "enqueue_work_session_action"]
    dispatch_hits = [hit for hit in hits if hit.action == "enqueue_claude_dispatch"]
    assert len(card_hits) == 6
    assert len(dispatch_hits) == 1
    left = [hit for hit in card_hits if hit.rect.x < tl_area.x + tl_area.w / 2]
    right = [hit for hit in card_hits if hit.rect.x >= tl_area.x + tl_area.w / 2]
    assert len(left) == len(right) == 3
    assert all(hit.rect.h >= 108 for hit in card_hits)
    assert max(hit.rect.x + hit.rect.w for hit in left) < min(hit.rect.x for hit in right)
    assert min(hit.rect.x for hit in right) - max(hit.rect.x + hit.rect.w for hit in left) >= 120


def test_center_workbench_dispatch_is_always_visible_and_within_bounds():
    from deskbar.layout import Rect

    surface = pygame.Surface((1920, 480))
    tl_area = Rect(420, 52, 1100, 368)
    codex_only = Snapshot([], None, {}, 0, work_sessions=WorkSessionSnapshot((
        WorkSessionItem("codex", "task", NOW - timedelta(minutes=1), "opaque-open-id-codex-only"),
    )))

    hits = worksessionwidget.render_center_view(surface, codex_only, Settings(), tl_area, NOW)
    assert sum(hit.action == "enqueue_claude_dispatch" for hit in hits) == 1
    for hit in hits:
        assert tl_area.x <= hit.rect.x
        assert tl_area.y <= hit.rect.y
        assert hit.rect.x + hit.rect.w <= tl_area.x + tl_area.w
        assert hit.rect.y + hit.rect.h <= tl_area.y + tl_area.h
