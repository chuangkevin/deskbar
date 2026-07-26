from datetime import datetime
from zoneinfo import ZoneInfo
from deskbar.alarms import AlarmStore

TZ = ZoneInfo("Asia/Taipei")


def mk(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = AlarmStore()
    s.load()
    return s


def T(h, m, wd=0):  # 2026-07-27 是週一（weekday 0）
    return datetime(2026, 7, 27 + wd, h, m, tzinfo=TZ)


def test_add_persist_roundtrip(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [0, 1, 2, 3, 4], "打卡")
    s2 = mk(tmp_path, monkeypatch)
    got = s2.list()
    assert len(got) == 1 and got[0].id == a.id and got[0].label == "打卡"
    assert got[0].days == [0, 1, 2, 3, 4] and got[0].enabled


def test_due_fires_once_crossing_minute(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    s.add("09:00", [], "test")
    assert s.due(T(8, 59), T(9, 0)) != []
    assert s.due(T(9, 0), T(9, 1)) == []  # 已停用（一次性）


def test_one_shot_disables_after_fire(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    s.add("09:00", [], "once")
    s.due(T(8, 59), T(9, 0))
    assert s.list()[0].enabled is False
    s2 = mk(tmp_path, monkeypatch)          # 停用有存檔
    assert s2.list()[0].enabled is False


def test_weekday_filter(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    s.add("09:00", [0], "mon-only")          # 只有週一
    assert s.due(T(8, 59, wd=0), T(9, 0, wd=0)) != []   # 週一響
    s.set_enabled(s.list()[0].id, True)
    assert s.due(T(8, 59, wd=1), T(9, 0, wd=1)) == []   # 週二不響


def test_disabled_not_due_and_remove(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [], "x")
    s.set_enabled(a.id, False)
    assert s.due(T(8, 59), T(9, 0)) == []
    assert s.remove(a.id) is True and s.list() == []
    assert s.remove("nope") is False
