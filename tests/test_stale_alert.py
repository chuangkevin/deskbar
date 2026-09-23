"""tools/stale_alert.py：跑在另一台機器上定時看 deskbar /api/usage，
太久沒更新就 Slack 私訊 Kevin，恢復時再發一次。只測純函數 evaluate()。"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
NOW = datetime(2026, 9, 23, 4, 30, tzinfo=timezone.utc)  # 台北 12:30


def _load():
    path = TOOLS_DIR / "stale_alert.py"
    spec = importlib.util.spec_from_file_location("stale_alert_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _payload(fetched_ago_s=60, sections=None):
    return {
        "fetched_at": (NOW - timedelta(seconds=fetched_ago_s)).isoformat(),
        "sections": sections if sections is not None else [
            {"key": "claude", "title": "CLAUDE CODE", "age_s": 120.0, "muted": False},
            {"key": "antigravity", "title": "ANTIGRAVITY · GEMINI", "age_s": 200.0, "muted": False},
        ],
    }


def test_fresh_data_no_message_and_empty_state():
    m = _load()
    state, messages = m.evaluate(_payload(), NOW, {})
    assert messages == []
    assert state["problems"] == []


def test_14_minutes_old_is_not_an_alert():
    m = _load()
    _, messages = m.evaluate(_payload(fetched_ago_s=14 * 60), NOW, {})
    assert messages == []


def test_16_minutes_old_alerts_once_with_minutes_and_taipei_time():
    m = _load()
    state, messages = m.evaluate(_payload(fetched_ago_s=16 * 60), NOW, {})
    assert len(messages) == 1
    first_line = messages[0].splitlines()[0]
    assert "16 分鐘沒更新" in first_line
    assert len(first_line) <= 30
    assert "12:14" in messages[0]  # 最後資料時間用台北時間
    assert state["problems"] == ["stale"]


def test_still_stale_later_does_not_repeat():
    m = _load()
    state, _ = m.evaluate(_payload(fetched_ago_s=16 * 60), NOW, {})
    state, messages = m.evaluate(_payload(fetched_ago_s=30 * 60), NOW, state)
    assert messages == []
    assert state["problems"] == ["stale"]


def test_recovery_sends_one_message_then_quiet():
    m = _load()
    state, _ = m.evaluate(_payload(fetched_ago_s=16 * 60), NOW, {})
    state, messages = m.evaluate(_payload(fetched_ago_s=30), NOW, state)
    assert len(messages) == 1
    assert "恢復" in messages[0].splitlines()[0]
    assert state["problems"] == []
    state, messages = m.evaluate(_payload(fetched_ago_s=30), NOW, state)
    assert messages == []


def test_unreachable_alerts_down():
    m = _load()
    state, messages = m.evaluate(None, NOW, {})
    assert len(messages) == 1
    assert "連不上" in messages[0].splitlines()[0]
    assert state["problems"] == ["down"]
    state, messages = m.evaluate(None, NOW, state)
    assert messages == []


def test_missing_fetched_at_counts_as_stale():
    m = _load()
    payload = _payload()
    payload["fetched_at"] = None
    state, messages = m.evaluate(payload, NOW, {})
    assert state["problems"] == ["stale"]
    assert len(messages) == 1


def test_single_section_over_one_hour_alerts_with_its_title():
    m = _load()
    sections = [
        {"key": "claude", "title": "CLAUDE CODE", "age_s": 3700.0, "muted": False},
        {"key": "antigravity", "title": "ANTIGRAVITY · GEMINI", "age_s": 100.0, "muted": False},
    ]
    state, messages = m.evaluate(_payload(sections=sections), NOW, {})
    assert state["problems"] == ["section:claude"]
    assert len(messages) == 1
    assert "CLAUDE CODE" in messages[0]
    assert "ANTIGRAVITY" not in messages[0]
    assert len(messages[0].splitlines()[0]) <= 30


def test_muted_section_is_ignored():
    m = _load()
    sections = [{"key": "openai:x", "title": "OPENAI · c2", "age_s": 99999.0, "muted": True}]
    state, messages = m.evaluate(_payload(sections=sections), NOW, {})
    assert messages == []
    assert state["problems"] == []


def test_new_section_problem_alerts_but_known_one_does_not_repeat():
    m = _load()
    old = [{"key": "claude", "title": "CLAUDE CODE", "age_s": 3700.0, "muted": False},
           {"key": "antigravity", "title": "ANTIGRAVITY · GEMINI", "age_s": 100.0, "muted": False}]
    state, _ = m.evaluate(_payload(sections=old), NOW, {})
    both = [{"key": "claude", "title": "CLAUDE CODE", "age_s": 4000.0, "muted": False},
            {"key": "antigravity", "title": "ANTIGRAVITY · GEMINI", "age_s": 3800.0, "muted": False}]
    state, messages = m.evaluate(_payload(sections=both), NOW, state)
    assert state["problems"] == ["section:antigravity", "section:claude"]
    assert len(messages) == 1
    assert "ANTIGRAVITY" in messages[0]
    assert "CLAUDE CODE" not in messages[0]


def test_whole_payload_stale_suppresses_section_alerts():
    """整包都停了，每一區自然也舊；只發一則「整包沒更新」，不要再逐區洗版。"""
    m = _load()
    sections = [{"key": "claude", "title": "CLAUDE CODE", "age_s": 5000.0, "muted": False}]
    state, messages = m.evaluate(_payload(fetched_ago_s=20 * 60, sections=sections), NOW, {})
    assert state["problems"] == ["stale"]
    assert len(messages) == 1


def test_section_without_age_is_skipped_not_crash():
    m = _load()
    sections = [{"key": "claude", "title": "CLAUDE CODE", "age_s": None, "muted": False}]
    state, messages = m.evaluate(_payload(sections=sections), NOW, {})
    assert messages == []
    assert state["problems"] == []


def test_naive_fetched_at_is_treated_as_utc():
    m = _load()
    payload = _payload()
    payload["fetched_at"] = (NOW - timedelta(minutes=20)).replace(tzinfo=None).isoformat()
    state, messages = m.evaluate(payload, NOW, {})
    assert state["problems"] == ["stale"]
    assert "20 分鐘沒更新" in messages[0]
