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


def test_arrival_alarm_waits_for_phone_and_fires_once_per_day(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [0], "打卡", arrival_trigger=True)

    # 既有時間鬧鐘路徑不得提早響；人到了才由到場路徑提醒。
    assert s.due(T(8, 59), T(9, 0)) == []
    assert s.due_on_arrival(T(9, 5), phone_present=False) == []
    fired = s.due_on_arrival(T(9, 5), phone_present=True)
    assert [x.id for x in fired] == [a.id]
    assert s.due_on_arrival(T(10, 0), phone_present=True) == []

    # 成功日期寫入檔案，重開後也不會重複提醒。
    assert mk(tmp_path, monkeypatch).due_on_arrival(T(10, 0), phone_present=True) == []


def test_arrival_alarm_respects_skip_and_one_shot(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    skipped = s.add("09:00", [0], "打卡", arrival_trigger=True)
    s.set_skip_date(skipped.id, "2026-07-27")
    assert s.due_on_arrival(T(9, 5), phone_present=True) == []

    once = s.add("09:00", [], "一次", arrival_trigger=True)
    assert [x.id for x in s.due_on_arrival(T(9, 5), phone_present=True)] == [once.id]
    assert {a.id: a.enabled for a in s.list()}[once.id] is False


def test_arrival_trigger_normalizes_and_can_be_changed(tmp_path, monkeypatch):
    from deskbar.alarms import _normalize_alarm
    a = _normalize_alarm({"id": "a1", "time": "09:00", "arrival_trigger": True,
                          "arrival_fired_date": "2026-07-27"})
    assert a is not None and a.arrival_trigger and a.arrival_fired_date == "2026-07-27"
    assert _normalize_alarm({"id": "a1", "time": "09:00", "arrival_trigger": "yes"}).arrival_trigger is False

    s = mk(tmp_path, monkeypatch)
    created = s.add("09:00", [0], "打卡")
    assert s.set_arrival_trigger(created.id, True)
    assert s.list()[0].arrival_trigger is True


def test_update_changes_editable_fields_atomically(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [0], "舊標籤")
    assert s.update(a.id, time="08:45", days=[4, 1, 1], label="打卡", arrival_trigger=True)
    got = s.list()[0]
    assert (got.time, got.days, got.label, got.arrival_trigger) == ("08:45", [1, 4], "打卡", True)

    # 壞輸入不可留下半套修改。
    assert not s.update(a.id, time="99:00", label="不應寫入")
    got = s.list()[0]
    assert (got.time, got.label) == ("08:45", "打卡")


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


def test_normalize_alarm_skip_date():
    from deskbar.alarms import _normalize_alarm
    a = _normalize_alarm({"id": "a1", "time": "09:00", "skip_date": "2026-08-06"})
    assert a is not None and a.skip_date == "2026-08-06"

    assert _normalize_alarm({"id": "a1", "time": "09:00", "skip_date": 123}).skip_date is None
    assert _normalize_alarm({"id": "a1", "time": "09:00", "skip_date": "2026-8-6"}).skip_date is None
    assert _normalize_alarm({"id": "a1", "time": "09:00", "skip_date": "2026-13-45"}).skip_date is None


def test_due_skip_date_today_yesterday_tomorrow(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a1 = s.add("09:00", [0], "today-skip")
    s.set_skip_date(a1.id, "2026-07-27")

    a2 = s.add("09:00", [0], "yesterday-skip")
    s.set_skip_date(a2.id, "2026-07-26")

    a3 = s.add("09:00", [0], "tomorrow-skip")
    s.set_skip_date(a3.id, "2026-07-28")

    now = T(9, 0, wd=0)
    last = T(8, 59, wd=0)
    fired = s.due(last, now)
    fired_ids = {a.id for a in fired}

    assert a1.id not in fired_ids
    assert a2.id in fired_ids
    # 搜尋 store 中對應的 alarm 檢查過期的 skip_date 是否已被清空
    store_alarms = {a.id: a for a in s.list()}
    assert store_alarms[a2.id].skip_date is None
    assert a3.id in fired_ids
    assert store_alarms[a3.id].skip_date == "2026-07-28"


def test_due_one_shot_skip_date_not_disabled(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [], "one-shot")
    s.set_skip_date(a.id, "2026-07-27")

    now = T(9, 0, wd=0)
    last = T(8, 59, wd=0)
    fired = s.due(last, now)
    assert fired == []
    assert s.list()[0].enabled is True


def test_due_disabled_and_skipped_coexist(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [0], "disabled-and-skipped")
    s.set_enabled(a.id, False)
    s.set_skip_date(a.id, "2026-07-27")

    fired = s.due(T(8, 59, wd=0), T(9, 0, wd=0))
    assert fired == []


def test_set_skip_date(tmp_path, monkeypatch):
    s = mk(tmp_path, monkeypatch)
    a = s.add("09:00", [0], "test")

    assert s.set_skip_date(a.id, "2026-08-06") is True
    assert s.list()[0].skip_date == "2026-08-06"

    assert s.set_skip_date(a.id, "invalid-date") is False
    assert s.list()[0].skip_date == "2026-08-06"

    assert s.set_skip_date("nope", "2026-08-06") is False

    assert s.set_skip_date(a.id, None) is True
    assert s.list()[0].skip_date is None
