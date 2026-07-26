"""transitions.py：切換過場 SlideTransition／開機 splash／迫近脈動 的純函數測試。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.models import Event
from deskbar.ui import transitions

TZ = ZoneInfo("Asia/Taipei")


def _surf(color):
    s = pygame.Surface((1920, 480))
    s.fill(color)
    return s


def _event(id_, start, all_day=False):
    return Event(id_, "a@x.com", "c", "t", start, start + timedelta(minutes=30), all_day,
                None, None)


# ---------------------------------------------------------------------------
# SlideTransition
# ---------------------------------------------------------------------------

def test_slide_transition_inactive_before_start():
    t = transitions.SlideTransition()
    assert t.active() is False


def test_slide_transition_composes_during_window_then_ends():
    old = _surf((10, 10, 10))
    new = _surf((200, 200, 200))
    t = transitions.SlideTransition()
    t.start(old, direction=1)
    assert t.active() is True

    # 0s：舊畫面幾乎原樣（尚未開始滑動）
    f0 = t.frame(new, 0.0)
    assert f0.get_size() == (1920, 480)
    assert tuple(f0.get_at((10, 240)))[:3] == (10, 10, 10)
    assert t.active() is True

    # 0.1s（DURATION 的一半）：畫面中段已滑動，右側露出新畫面
    f1 = t.frame(new, 0.1)
    assert tuple(f1.get_at((1910, 240)))[:3] == (200, 200, 200)
    assert tuple(f1.get_at((10, 240)))[:3] == (10, 10, 10)
    assert t.active() is True

    # 0.25s（超過 DURATION=0.2）：過場結束，直接回傳 new_surface 本身
    f2 = t.frame(new, 0.25)
    assert t.active() is False
    assert f2 is new


def test_slide_transition_direction_negative_slides_opposite_way():
    old = _surf((10, 10, 10))
    new = _surf((200, 200, 200))
    t = transitions.SlideTransition()
    t.start(old, direction=-1)
    f = t.frame(new, 0.1)
    # 反方向：新畫面從左側露出、舊畫面往右滑
    assert tuple(f.get_at((10, 240)))[:3] == (200, 200, 200)
    assert tuple(f.get_at((1910, 240)))[:3] == (10, 10, 10)


def test_slide_transition_frame_without_start_returns_new_untouched():
    t = transitions.SlideTransition()
    new = _surf((200, 200, 200))
    assert t.frame(new, 0.0) is new


def test_slide_transition_duration_constant():
    assert transitions.SlideTransition.DURATION == 0.2


# ---------------------------------------------------------------------------
# splash_frames
# ---------------------------------------------------------------------------

def test_splash_frames_length_and_size():
    frames = transitions.splash_frames(1920, 480, text="deskbar")
    assert len(frames) == 13
    for f in frames:
        assert isinstance(f, pygame.Surface)
        assert f.get_size() == (1920, 480)


def test_splash_frames_black_background_corners():
    frames = transitions.splash_frames(1920, 480)
    for f in (frames[0], frames[9], frames[-1]):
        assert tuple(f.get_at((0, 0)))[:3] == (0, 0, 0)
        assert tuple(f.get_at((1919, 479)))[:3] == (0, 0, 0)


def test_splash_frames_reveal_is_monotonic_over_first_ten():
    frames = transitions.splash_frames(1920, 480)
    brightness = []
    for f in frames[:10]:
        avg = pygame.transform.average_color(f)
        brightness.append(avg[0] + avg[1] + avg[2])
    assert brightness == sorted(brightness)
    assert brightness[0] < brightness[-1]     # 第一張跟最後一張確實不同（有掃光）


def test_splash_frames_last_three_fade_out():
    frames = transitions.splash_frames(1920, 480)
    fade = frames[10:13]
    assert len(fade) == 3
    brightness = []
    for f in fade:
        avg = pygame.transform.average_color(f)
        brightness.append(avg[0] + avg[1] + avg[2])
    # 淡出：逐張變暗（或持平），且最後一張比第一張淡出畫面更暗
    assert brightness[0] >= brightness[-1]


# ---------------------------------------------------------------------------
# pulse_border_color
# ---------------------------------------------------------------------------

def test_pulse_border_color_two_phases_differ_and_in_range():
    main = (93, 202, 165)
    t0 = datetime.fromtimestamp(0, tz=TZ)          # sin(0)=0 → 中間色
    t1 = datetime.fromtimestamp(0.5, tz=TZ)        # period=2.0 的 1/4 → sin=1 → 全白
    c0 = transitions.pulse_border_color(main, t0, period_s=2.0)
    c1 = transitions.pulse_border_color(main, t1, period_s=2.0)
    assert c0 != c1
    assert c1 == (255, 255, 255)
    for c in (c0, c1):
        assert len(c) == 3
        for ch in c:
            assert 0 <= ch <= 255


def test_pulse_border_color_stays_within_rgb_bounds_over_full_cycle():
    main = (240, 153, 123)
    for ms in range(0, 2000, 37):
        now = datetime.fromtimestamp(ms / 1000, tz=TZ)
        c = transitions.pulse_border_color(main, now, period_s=2.0)
        assert all(0 <= ch <= 255 for ch in c)


# ---------------------------------------------------------------------------
# imminent_ids
# ---------------------------------------------------------------------------

def test_imminent_ids_four_boundaries():
    now = datetime(2026, 7, 27, 10, 0, tzinfo=TZ)
    within = _event("in", now + timedelta(minutes=4, seconds=59))
    outside = _event("out", now + timedelta(minutes=5, seconds=1))
    started = _event("started", now - timedelta(minutes=1))
    allday = _event("allday", now + timedelta(minutes=1), all_day=True)

    ids = transitions.imminent_ids([within, outside, started, allday], now)
    assert ids == {"in"}


def test_imminent_ids_exact_window_edge_counts():
    now = datetime(2026, 7, 27, 10, 0, tzinfo=TZ)
    exactly_five = _event("edge", now + timedelta(minutes=5))
    ids = transitions.imminent_ids([exactly_five], now)
    assert ids == {"edge"}     # 含 5 分鐘整


def test_imminent_ids_respects_custom_window_min():
    now = datetime(2026, 7, 27, 10, 0, tzinfo=TZ)
    e = _event("e", now + timedelta(minutes=8))
    assert transitions.imminent_ids([e], now) == set()
    assert transitions.imminent_ids([e], now, window_min=10) == {"e"}
