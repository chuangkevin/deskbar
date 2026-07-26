from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.alarms import Alarm, AlarmStore
from deskbar.ui import alarm_view, theme

NOW = datetime(2026, 7, 27, 8, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def _max_brightness(surf, x0, y0, x1, y1) -> int:
    best = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = surf.get_at((x, y))[:3]
            best = max(best, r + g + b)
    return best


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


class _FixedStore:
    def __init__(self, alarms):
        self._alarms = alarms

    def list(self):
        return self._alarms


def test_disabled_alarm_row_is_dimmer_than_enabled_row():
    """規格：停用列整列（時間／標籤／星期）改 muted 色，跟啟用列要有明顯明暗差。
    直接比較兩列「時間」文字所在區域的最亮像素，停用列應該明顯暗於啟用列
    （theme.C["text"] 亮度 708 vs theme.C["muted"] 亮度 333，差距夠大不受
    反鋸齒邊緣影響）。"""
    alarms = [
        Alarm(id="a1", time="07:30", days=[0, 1, 2, 3, 4], label="打卡", enabled=True),
        Alarm(id="a2", time="21:30", days=[], label="吃藥", enabled=False),
    ]
    surf = pygame.Surface((1920, 480))
    alarm_view.render(surf, _FixedStore(alarms), _draft(), NOW)

    # _render_list：第一列 y=100，第二列 y=185（每列 +85），時間文字 40px 字。
    enabled_peak = _max_brightness(surf, 40, 100, 190, 150)
    disabled_peak = _max_brightness(surf, 40, 185, 190, 235)
    assert enabled_peak >= sum(theme.C["text"]) - 20
    assert disabled_peak <= sum(theme.C["muted"]) + 20
    assert enabled_peak - disabled_peak >= 200


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
