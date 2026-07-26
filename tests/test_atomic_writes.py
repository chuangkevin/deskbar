"""鬧鐘 (alarms.py) 與事件快取 (store.py) 的原子寫入行為。

兩者都比照 config.save_settings 的模式：tempfile.mkstemp 在目標同目錄開暫存檔
寫入，成功後才 os.replace 蓋過正式檔名。這裡驗證兩件事：

1. 確實走 os.replace 這條路徑（記錄呼叫、檢查來源/目的檔名）。
2. 寫入途中（json.dump 階段）失敗時，正式檔案完全不受影響——因為 os.replace
   根本沒被呼叫到，舊內容原封不動。
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from deskbar import alarms as alarms_mod
from deskbar import store as store_mod
from deskbar.alarms import AlarmStore
from deskbar.models import Event
from deskbar.store import AppState

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)
E = Event("e1", "a@x.com", "c", "T", NOW, NOW, False, None, None)


def _spy_replace(monkeypatch, target_mod):
    """monkeypatch target_mod.os.replace：記錄每次呼叫的 (src, dst)，
    但仍真的執行 os.replace，讓後續斷言可以檢查落地檔案內容。"""
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(target_mod.os, "replace", spy)
    return calls


# ---------- alarms.py ----------

def test_alarm_save_goes_through_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    calls = _spy_replace(monkeypatch, alarms_mod)

    s = AlarmStore()
    s.load()
    s.add("09:00", [], "打卡")

    assert len(calls) == 1
    src, dst = calls[0]
    assert dst == tmp_path / "alarms.json"
    assert not os.path.exists(src)          # 暫存檔已被 replace 掉，不留殘影
    saved = json.loads((tmp_path / "alarms.json").read_text(encoding="utf-8"))
    assert saved[0]["label"] == "打卡"


def test_alarm_save_failure_preserves_original_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = AlarmStore()
    s.load()
    s.add("09:00", [], "原始")
    original = (tmp_path / "alarms.json").read_text(encoding="utf-8")

    def boom(*a, **k):
        raise ValueError("json.dump 中途炸掉")

    monkeypatch.setattr(alarms_mod.json, "dump", boom)
    with pytest.raises(ValueError):
        s.add("10:00", [], "新的")

    assert (tmp_path / "alarms.json").read_text(encoding="utf-8") == original


# ---------- store.py ----------

def test_store_save_cache_goes_through_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    calls = _spy_replace(monkeypatch, store_mod)

    st = AppState()
    st.set_events("a@x.com", [E], NOW)
    st.save_cache()

    assert len(calls) == 1
    src, dst = calls[0]
    assert dst == tmp_path / "events.json"
    assert not os.path.exists(src)
    data = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    assert "a@x.com" in data


def test_store_save_cache_failure_preserves_original_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    st = AppState()
    st.set_events("a@x.com", [E], NOW)
    st.save_cache()
    original = (tmp_path / "events.json").read_text(encoding="utf-8")

    def boom(*a, **k):
        raise ValueError("json.dump 中途炸掉")

    monkeypatch.setattr(store_mod.json, "dump", boom)
    with pytest.raises(ValueError):
        st.save_cache()

    assert (tmp_path / "events.json").read_text(encoding="utf-8") == original
