from datetime import datetime
from zoneinfo import ZoneInfo
from deskbar.store import AppState
from deskbar.models import Event

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)
E = Event("e1", "a@x.com", "c", "T", NOW, NOW, False, None, None)


def test_set_events_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    st = AppState()
    s0 = st.snapshot().seq
    st.set_events("a@x.com", [E], NOW)
    snap = st.snapshot()
    assert snap.seq == s0 + 1
    assert snap.events == [E]
    assert snap.statuses["a@x.com"].ok is True


def test_error_keeps_old_events(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    st = AppState()
    st.set_events("a@x.com", [E], NOW)
    st.set_error("a@x.com", "token 失效", NOW)
    snap = st.snapshot()
    assert snap.events == [E]  # 舊資料保留
    assert snap.statuses["a@x.com"].ok is False
    assert "token" in snap.statuses["a@x.com"].error


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    st = AppState()
    st.set_events("a@x.com", [E], NOW)
    st.save_cache()
    st2 = AppState()
    st2.load_cache()
    assert st2.snapshot().events == [E]


def test_drop_account(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path))
    st = AppState()
    st.set_events("a@x.com", [E], NOW)
    st.drop_account("a@x.com")
    snap = st.snapshot()
    assert snap.events == [] and "a@x.com" not in snap.statuses
