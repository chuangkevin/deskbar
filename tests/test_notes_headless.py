"""便條牆：NotesStore CRUD/上限/原子載入、/api/notes 端點、notesview 渲染
契約（空狀態指引/便利貼卡/撕除確認/溢出）、note_tap 兩段撕、三態下拖曳
不誤觸。"""
from __future__ import annotations

import threading
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.config import Settings
from deskbar.notes import Note, NotesStore
from deskbar.store import AppState
from deskbar.ui import dashboard, notesview, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 30, 10, 0, tzinfo=TZ)
AREA = dashboard.TL_AREA


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _note(i, text="買咖啡豆"):
    return Note(f"n{i}", text, NOW.isoformat())


# ---------------------------------------------------------------- store

def test_store_add_trims_caps_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    st = NotesStore()
    assert st.add("   ") is None, "空白便條拒收"
    n = st.add("  記得回 SARA-4551  ")
    assert n is not None and n.text == "記得回 SARA-4551"
    long = st.add("x" * 900)
    assert len(long.text) == 500, "超長截斷"
    for i in range(40):
        st.add(f"note {i}")
    assert len(st.list()) == 30, "上限 30 張，擠掉最舊"
    assert st.list()[0].text == "note 39", "新的在前"
    st2 = NotesStore()
    st2.load()
    assert [x.id for x in st2.list()] == [x.id for x in st.list()], "重載一致"
    assert st.remove(st.list()[0].id) is True
    assert st.remove("nope") is False


# ---------------------------------------------------------------- API

@pytest.fixture
def client(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    ns = NotesStore()
    app = create_app(_FakeAlarms(), notes_store=ns)
    app.config["TESTING"] = True
    c = app.test_client()
    c._notes = ns
    return c


def test_notes_api_crud(client):
    assert client.get("/api/notes").get_json() == []
    r = client.post("/api/notes", json={"text": "  部署前先掃敏感字串  "})
    assert r.status_code == 201
    nid = r.get_json()["id"]
    assert r.get_json()["text"] == "部署前先掃敏感字串"
    assert client.post("/api/notes", json={"text": "   "}).status_code == 400
    assert client.post("/api/notes", json={"text": 123}).status_code == 400
    assert len(client.get("/api/notes").get_json()) == 1
    assert client.delete(f"/api/notes/{nid}").status_code == 204
    assert client.delete(f"/api/notes/{nid}").status_code == 404


def test_notes_api_unavailable_without_store(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    app = create_app(_FakeAlarms())
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.get("/api/notes").status_code == 501


# ---------------------------------------------------------------- notesview

def test_notesview_empty_state_teaches_capture_paths():
    s = _surf()
    base = pygame.image.tobytes(s, "RGB")
    notesview.render(s, [], notesview.new_state(), AREA, NOW, 0.0)
    assert pygame.image.tobytes(s, "RGB") != base, "空牆要畫輸入指引"


def test_notesview_renders_sticky_cards_and_overflow():
    s = _surf()
    hits = notesview.render(s, [_note(i, f"便條內容 {i}") for i in range(8)],
                            notesview.new_state(), AREA, NOW, 0.0)
    assert len(hits) == 6, "最多 6 張上牆，其餘計數"
    assert all(h.action == "note_tap" for h in hits)
    blank = _surf()
    assert pygame.image.tobytes(s, "RGB") != pygame.image.tobytes(blank, "RGB")


def test_notesview_pending_overlay_and_timeout():
    ui = notesview.new_state()
    ui.update(pending_id="n0", pending_at=100.0)
    a = _surf()
    notesview.render(a, [_note(0)], dict(ui), AREA, NOW, 101.0)     # 確認中
    b = _surf()
    fresh = notesview.render.__wrapped__ if hasattr(notesview.render, "__wrapped__") else None
    ui2 = dict(ui)
    notesview.render(b, [_note(0)], ui2, AREA, NOW,
                     100.0 + notesview.PENDING_TIMEOUT_S + 1)       # 逾時回復
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB")
    assert ui2["pending_id"] is None, "逾時要自動清除確認狀態"


# ---------------------------------------------------------------- dispatch：兩段撕

def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    ns = NotesStore()
    ns.add("待撕便條")
    app = App(AppState(), Settings(), threading.Lock(), on_save=lambda s: None,
              alarm_store=None, notes_store=ns)
    app.settings.center_view = "notes"
    app.logical = pygame.Surface((1920, 480))
    app._flip = lambda: None
    return app


def test_note_tap_two_stage_tear(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW,
                                notes_store=app.notes_store, notes_ui=app.notes_ui)
    hit = next(h for h in app.hits if h.action == "note_tap")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert app.notes_ui["pending_id"] == hit.data, "第一次點＝進入確認"
    assert len(app.notes_store.list()) == 1, "第一次點不刪"
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert app.notes_store.list() == [], "第二次點＝撕掉"
    assert app.notes_ui["pending_id"] is None


def test_note_tap_confirm_expires(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW,
                                notes_store=app.notes_store, notes_ui=app.notes_ui)
    hit = next(h for h in app.hits if h.action == "note_tap")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    app.notes_ui["pending_at"] -= (notesview.PENDING_TIMEOUT_S + 1)   # 模擬逾時
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert len(app.notes_store.list()) == 1, "逾時後的點擊＝重新進入確認，不是刪除"
    assert app.notes_ui["pending_id"] == hit.data