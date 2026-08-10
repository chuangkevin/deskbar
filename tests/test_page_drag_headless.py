"""待辦/便條牆跟手拖曳與吸附翻頁 headless 測試。"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar import transform
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui.app import (App, DRAG_FPS, PAN_BAND_INTERVAL,
                            PAN_BAND_INTERVAL_DRAG, PAGE_FLIP_RATIO, loop_fps,
                            page_drag_decision, page_drag_offset, rot_offset,
                            should_prefetch)
from deskbar.ui.dashboard import CENTER_SLIDE_AREA, TL_X0, TL_X1

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)


# ---------------------------------------------------------------------------
# 任務 D：純函數測試
# ---------------------------------------------------------------------------

def test_loop_fps_uses_drag_rate_only_while_dragging():
    assert loop_fps(True) == DRAG_FPS == 60
    assert loop_fps(False) == 30
    assert loop_fps(False, 10) == 10
    assert PAN_BAND_INTERVAL_DRAG < PAN_BAND_INTERVAL

def test_page_drag_offset_cases():
    # 有下一頁、dx=-100、width=800 → -100 (1:1)
    assert page_drag_offset(-100, 800, has_prev=True, has_next=True) == -100.0

    # 沒有下一頁、dx=-90 → -30 (阻尼 /3)
    assert page_drag_offset(-90, 800, has_prev=True, has_next=False) == -30.0

    # 沒有上一頁、dx=+90 → +30 (阻尼 /3)
    assert page_drag_offset(90, 800, has_prev=False, has_next=True) == 30.0

    # dx 超過 width → 夾在 ±width
    assert page_drag_offset(-1000, 800, has_prev=True, has_next=True) == -800.0
    assert page_drag_offset(1000, 800, has_prev=True, has_next=True) == 800.0

    # dx=0 → 0
    assert page_drag_offset(0, 800, has_prev=True, has_next=True) == 0.0


def test_page_drag_decision_cases():
    # width=800、dx=-250 (>25%)、has_next=True → +1
    assert page_drag_decision(-250, 800, has_prev=True, has_next=True) == 1

    # dx=-100 (<25%) → 0
    assert page_drag_decision(-100, 800, has_prev=True, has_next=True) == 0

    # dx=+250、has_prev=True → -1
    assert page_drag_decision(250, 800, has_prev=True, has_next=True) == -1

    # dx=-250 但 has_next=False → 0
    assert page_drag_decision(-250, 800, has_prev=True, has_next=False) == 0

    # dx=0 → 0
    assert page_drag_decision(0, 800, has_prev=True, has_next=True) == 0


def test_rot_offset_cardinal_angles():
    assert rot_offset(12, 0) == (12, 0.0)
    assert rot_offset(-12, 0) == (-12, 0.0)

    assert rot_offset(12, 180) == (-12, 0.0)
    assert rot_offset(-12, 180) == (12, 0.0)

    assert rot_offset(12, -90) == (0.0, 12)
    assert rot_offset(-12, -90) == (0.0, -12)

    assert rot_offset(12, 90) == (0.0, -12)
    assert rot_offset(-12, 90) == (0.0, 12)


def test_rot_offset_unsupported_angle_degrades_to_logical_axis():
    assert rot_offset(12, 45) == (12, 0.0)
    assert rot_offset(-12, 45) == (-12, 0.0)


def test_prefetch_waits_for_full_idle_threshold():
    assert should_prefetch(idle_since=10.0, now_mono=11.999, threshold=2.0) is False


def test_prefetch_starts_at_idle_threshold():
    assert should_prefetch(idle_since=10.0, now_mono=12.0, threshold=2.0) is True


def test_input_resets_prefetch_idle_since(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app._idle_since = 10.0
    app.firing = [object()]
    app._firing_since = float("inf")
    monkeypatch.setattr(
        pygame.event, "get",
        lambda: [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r)],
    )
    monkeypatch.setattr(app, "_cycle_dev_rotate", lambda: None)
    monkeypatch.setattr(app, "_render", lambda: None)

    class Clock:
        def tick(self, _fps):
            pass

    app._run_iteration(Clock(), running=True)

    assert app._idle_since == 0.0


# ---------------------------------------------------------------------------
# 任務 D：Headless 渲染測試
# ---------------------------------------------------------------------------

def _issue(ident):
    from deskbar.linear import LinearIssue
    return LinearIssue(identifier=f"DESK-{ident}", title=f"Task {ident}", state_name="In Progress",
                       state_type="started", state_color="#5e6ad2", priority=1,
                       due=None, project="")


def _make_app(tmp_path, monkeypatch, center_view="linear", dev=False,
              physical_screen=False) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    # 填充一些 linear 任務以利分頁（1 頁可容納 6 項，餵 12 項會產生第 2 頁）
    state.set_linear([_issue(i) for i in range(12)], NOW)
    settings = Settings()
    settings.center_view = center_view
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None)
    app.view = "dashboard"
    app.logical = pygame.Surface((1920, 480))
    app._dev = dev
    app._dev_rotate = 0
    if dev:
        app.win = (1920, 480)
        app.screen = pygame.Surface(app.win)
    elif physical_screen:
        app.screen = pygame.Surface((480, 1920))
    else:
        app.screen = app.logical
    return app


def test_render_page_drag_band_calendar_returns_early(tmp_path, monkeypatch):
    """中欄為 calendar 時，_render_page_drag_band 直接 return，不建立 _page_drag。"""
    app = _make_app(tmp_path, monkeypatch, center_view="calendar")
    app._drag_start = (TL_X0 + 100, 100)
    app._drag_last = (TL_X0 + 200, 100)

    app._render_page_drag_band()
    assert app._page_drag is None


def test_render_page_drag_band_executes_without_exception_and_restores_page(tmp_path, monkeypatch):
    """拖曳中呼叫 _render_page_drag_band 不拋例外，且離線渲染後 center_pages 必須還原。"""
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)  # 往左拖看下一頁

    # 執行跟手渲染
    app._render_page_drag_band()

    # 驗證 1：_page_drag 已被建立且未拋例外
    assert app._page_drag is not None
    assert app._page_drag["center"] == "linear"
    assert app._page_drag["has_next"] is True
    assert app._page_drag["neighbour"] is not None

    # 驗證 2：離線渲染鄰頁後，center_pages["linear"] 必須被還原成原值 0
    assert app.center_pages["linear"] == 0


def test_render_page_drag_band_uses_prefetched_neighbour_without_redraw(tmp_path, monkeypatch):
    """鄰頁已預取時，拖曳起手不能再同步重畫昂貴頁面。"""
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    prefetched = pygame.Surface((int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h)))
    prefetched.fill((23, 45, 67))
    app._band_cache = {("linear", 1): prefetched}
    snap = app.state.snapshot()
    app._band_cache_key = ("linear", snap.seq, len(snap.linear))

    draw_calls = []
    monkeypatch.setattr(app, "_draw_frame", lambda *_args, **_kwargs: draw_calls.append(1))
    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)

    app._render_page_drag_band()

    assert app._page_drag is not None
    assert app._page_drag["neighbour"] is prefetched
    assert draw_calls == []


def test_first_idle_iteration_only_starts_prefetch_timer(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    calls = []
    monkeypatch.setattr(app, "_prefetch_page_band",
                        lambda *_args: calls.append(1) or True)
    monkeypatch.setattr("deskbar.ui.app.time.monotonic", lambda: 20.0)

    assert app._prefetch_page_band_if_idle(app.state.snapshot(), NOW) is False
    assert app._idle_since == 20.0
    assert calls == []


def test_successful_prefetch_restarts_full_idle_wait(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app._idle_since = 10.0
    calls = []
    monkeypatch.setattr(app, "_prefetch_page_band",
                        lambda *_args: calls.append(1) or True)
    monotonic_values = iter((12.0, 12.1, 14.099))
    monkeypatch.setattr("deskbar.ui.app.time.monotonic", monotonic_values.__next__)

    assert app._prefetch_page_band_if_idle(app.state.snapshot(), NOW) is True
    assert app._idle_since == 12.1
    assert app._prefetch_page_band_if_idle(app.state.snapshot(), NOW) is False
    assert calls == [1]


def test_prefetch_page_band_does_nothing_during_drag(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    cached = pygame.Surface((2, 2))
    app._band_cache = {("linear", 7): cached}
    app._band_cache_key = ("linear", -1, 99)
    app._drag_start = (TL_X0 + 10, 20)

    assert app._prefetch_page_band(app.state.snapshot(), NOW) is False
    assert app._band_cache == {("linear", 7): cached}
    assert app._band_cache_key == ("linear", -1, 99)


def test_prefetch_page_band_ignores_calendar(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="calendar")

    assert app._prefetch_page_band(app.state.snapshot(), NOW) is False
    assert app._band_cache == {}
    assert app._band_cache_key is None


def test_prefetch_page_band_adds_one_neighbour_and_restores_page(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    monkeypatch.setattr(app, "_draw_frame", lambda *_args, **_kwargs: None)
    snap = app.state.snapshot()

    assert app._prefetch_page_band(snap, NOW) is True
    assert set(app._band_cache) == {("linear", 1)}
    assert app._band_cache_key == ("linear", snap.seq, len(snap.linear))
    assert app.center_pages["linear"] == 0


def test_prefetch_page_band_fills_both_sides_one_at_a_time(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.state.set_linear([_issue(i) for i in range(24)], NOW)
    app.center_pages["linear"] = 1
    monkeypatch.setattr(app, "_draw_frame", lambda *_args, **_kwargs: None)
    snap = app.state.snapshot()

    assert app._prefetch_page_band(snap, NOW) is True
    assert set(app._band_cache) == {("linear", 0)}
    assert app.center_pages["linear"] == 1

    assert app._prefetch_page_band(snap, NOW) is True
    assert set(app._band_cache) == {("linear", 0), ("linear", 2)}
    assert app.center_pages["linear"] == 1

    assert app._prefetch_page_band(snap, NOW) is False
    assert app.center_pages["linear"] == 1


def test_prefetch_page_band_rebuilds_after_snapshot_sequence_changes(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    monkeypatch.setattr(app, "_draw_frame", lambda *_args, **_kwargs: None)
    first_snap = app.state.snapshot()
    assert app._prefetch_page_band(first_snap, NOW) is True
    first_band = app._band_cache[("linear", 1)]

    app.state.set_linear([_issue(i) for i in range(12)], NOW)
    second_snap = app.state.snapshot()
    assert second_snap.seq != first_snap.seq
    assert app._prefetch_page_band(second_snap, NOW) is True

    assert set(app._band_cache) == {("linear", 1)}
    assert app._band_cache[("linear", 1)] is not first_band
    assert app._band_cache_key == ("linear", second_snap.seq, len(second_snap.linear))


def test_prefetch_page_band_failure_is_silent_and_restores_state(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    app.logical.fill((11, 22, 33))
    old_hits = app.hits

    def fail_draw(*_args, **_kwargs):
        app.logical.fill((200, 10, 20))
        app.hits = [object()]
        raise RuntimeError("render failed")

    monkeypatch.setattr(app, "_draw_frame", fail_draw)

    assert app._prefetch_page_band(app.state.snapshot(), NOW) is False
    assert app.center_pages["linear"] == 0
    assert app._band_cache == {}
    assert app.hits is old_hits
    assert app.logical.get_at((0, 0))[:3] == (11, 22, 33)


def test_prefetch_page_band_keeps_only_four_most_recent_pages(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.state.set_linear([_issue(i) for i in range(48)], NOW)
    monkeypatch.setattr(app, "_draw_frame", lambda *_args, **_kwargs: None)
    snap = app.state.snapshot()

    for page in range(6):
        app.center_pages["linear"] = page
        for _ in range(3):
            if not app._prefetch_page_band(snap, NOW):
                break
            assert len(app._band_cache) <= 4

    assert set(app._band_cache) == {
        ("linear", 2), ("linear", 3), ("linear", 4), ("linear", 5),
    }


def test_touch_up_triggers_page_settle_and_flips_page(tmp_path, monkeypatch):
    """放手且拖曳超過 25% 時，觸發 _page_settle 動畫並翻到下一頁。"""
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    start_x = TL_X0 + 300
    app._drag_start = (start_x, 100)
    # 中欄實際寬度是 CENTER_SLIDE_AREA.w（1118），門檻＝25%＝279.5px，
    # 所以拖曳量要用實際寬度算，不能寫死魔術數字（原本寫 250 以為門檻是
    # 800*0.25=200，實機上根本不到門檻、正確行為是彈回，測試因此紅掉）。
    drag_px = int(CENTER_SLIDE_AREA.w * PAGE_FLIP_RATIO) + 20
    app._drag_last = (start_x - drag_px, 100)

    # 模擬拖曳中的一幀
    app._render_page_drag_band()
    assert app._page_drag is not None

    # 放手
    app._handle_touch_up(start_x - drag_px, 100)

    # 驗證頁碼已更新成 1 且開啟 _page_settle 吸附動畫
    assert app.center_pages["linear"] == 1
    assert app._page_settle is not None
    assert app._page_settle["to"] == -app._page_drag["rect"].w

    # 驅動動畫直至結束
    app._page_settle["start"] -= 1.0  # 模擬過期 > 0.15s
    app._render_page_settle_frame(NOW)

    # 驗證動畫結束清空狀態
    assert app._page_drag is None
    assert app._page_settle is None


def test_render_page_drag_band_precomputes_rotated_snapshots(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear", physical_screen=True)
    app.center_pages["linear"] = 0
    app.logical.fill((12, 34, 56))
    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)

    app._render_page_drag_band()

    assert app._page_drag is not None
    assert app._page_drag["angle"] == transform.pygame_rotation_angle(app.settings.rotation)
    assert app._page_drag["rot_base"] == app._map_rot(
        pygame.Rect(int(CENTER_SLIDE_AREA.x), int(CENTER_SLIDE_AREA.y),
                    int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h)),
        app._page_drag["angle"])
    assert app._page_drag["cur_rot"].get_size() == (
        int(CENTER_SLIDE_AREA.h), int(CENTER_SLIDE_AREA.w))


def test_render_page_drag_band_dev_keeps_old_path_without_rotated_snapshot(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear", dev=True)
    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)

    app._render_page_drag_band()

    assert app._page_drag is not None
    assert "cur_rot" not in app._page_drag
    assert "angle" not in app._page_drag
    assert "rot_base" not in app._page_drag


def test_render_page_drag_band_rotates_only_when_drag_state_is_created(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear", physical_screen=True)
    app.center_pages["linear"] = 0
    angle = transform.pygame_rotation_angle(app.settings.rotation)
    original_rotate = pygame.transform.rotate
    app._rot_cache = original_rotate(app.logical, angle)
    app._rot_angle = angle

    def fake_draw_frame(*_args, **_kwargs):
        app.logical.fill((90, 40, 10))

    monkeypatch.setattr(app, "_draw_frame", fake_draw_frame)

    calls = []

    def counted_rotate(surface, rotate_angle):
        calls.append(rotate_angle)
        return original_rotate(surface, rotate_angle)

    monkeypatch.setattr(pygame.transform, "rotate", counted_rotate)

    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)

    app._render_page_drag_band()
    first_count = len(calls)
    assert first_count == 2

    for delta in (140, 180, 220):
        app._drag_last = (start_x - delta, 100)
        app._page_drag_at -= 1.0
        app._render_page_drag_band()

    assert len(calls) == first_count


def test_page_settle_finish_invalidates_rot_cache_for_next_full_rebuild(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch, center_view="linear", physical_screen=True)
    app.center_pages["linear"] = 0
    angle = transform.pygame_rotation_angle(app.settings.rotation)
    app._rot_cache = pygame.transform.rotate(app.logical, angle)
    app._rot_angle = angle

    start_x = TL_X0 + 300
    drag_px = int(CENTER_SLIDE_AREA.w * PAGE_FLIP_RATIO) + 20
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - drag_px, 100)
    app._render_page_drag_band()
    app._handle_touch_up(start_x - drag_px, 100)
    assert app._page_settle is not None

    monkeypatch.setattr(app, "_render", lambda: None)
    old_cache = app._rot_cache
    app._page_settle["start"] -= 1.0
    app._render_page_settle_frame(NOW)

    assert app._page_drag is None
    assert app._page_settle is None
    assert app._last_seq == -1
    assert app._rot_angle is None

    app._flip(None)
    assert app._rot_angle == angle
    assert app._rot_cache is not old_cache
