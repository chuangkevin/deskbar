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
    assert all(h.action == "note_arm" for h in hits)
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
    app._flip = lambda *a, **k: None
    return app


def _rerender(app):
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW,
                                notes_store=app.notes_store, notes_ui=app.notes_ui)


def test_note_tear_requires_x_button(tmp_path, monkeypatch):
    """誤觸防呆：武裝後點卡上非 ✕ 區＝取消；只有點中 ✕ 小目標才真的撕。"""
    app = _make_app(tmp_path, monkeypatch)
    _rerender(app)
    hit = next(h for h in app.hits if h.action == "note_arm")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert app.notes_ui["pending_id"] == hit.data, "第一次點＝武裝"
    assert len(app.notes_store.list()) == 1, "武裝不刪"
    _rerender(app)
    cancel = next(h for h in app.hits if h.action == "note_cancel")
    app._dispatch(cancel.rect.x + 5, cancel.rect.y + cancel.rect.h - 5)  # 左下＝遠離 ✕
    assert app.notes_ui["pending_id"] is None, "點非 ✕ 區＝取消"
    assert len(app.notes_store.list()) == 1, "取消不刪"
    _rerender(app)
    hit = next(h for h in app.hits if h.action == "note_arm")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    _rerender(app)
    xbtn = next(h for h in app.hits if h.action == "note_del")
    app._dispatch(xbtn.rect.x + 5, xbtn.rect.y + 5)
    assert app.notes_store.list() == [], "點中 ✕ 才撕"
    assert app.notes_ui["pending_id"] is None


def test_note_tap_confirm_expires(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    _rerender(app)
    hit = next(h for h in app.hits if h.action == "note_arm")
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    app.notes_ui["pending_at"] -= (notesview.PENDING_TIMEOUT_S + 1)   # 模擬逾時
    _rerender(app)   # 逾時的武裝在重繪時自動解除 → 又回到 note_arm
    app._dispatch(hit.rect.x + 5, hit.rect.y + 5)
    assert len(app.notes_store.list()) == 1, "逾時後的點擊＝重新武裝，不是刪除"
    assert app.notes_ui["pending_id"] == hit.data

def test_store_update_edits_text_keeps_ts(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    st = NotesStore()
    n = st.add("原文")
    upd = st.update(n.id, "  改過的內容  ")
    assert upd.text == "改過的內容" and upd.ts == n.ts, "編輯保留捕捉時刻"
    assert st.list()[0].text == "改過的內容"
    assert st.update(n.id, "   ") is None, "空文字拒改"
    assert st.list()[0].text == "改過的內容"
    assert st.update("nope", "x") is None
    st2 = NotesStore(); st2.load()
    assert st2.list()[0].text == "改過的內容", "編輯要持久化"


def test_notes_api_patch_edits_and_bumps_render(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    ns = NotesStore()
    state = AppState()
    app = create_app(_FakeAlarms(), notes_store=ns, usage_state=state)
    app.config["TESTING"] = True
    c = app.test_client()
    seq0 = state.snapshot().seq
    nid = c.post("/api/notes", json={"text": "v1"}).get_json()["id"]
    assert state.snapshot().seq > seq0, "新增便條要叫醒 render 迴圈"
    r = c.patch(f"/api/notes/{nid}", json={"text": "v2"})
    assert r.status_code == 200 and r.get_json()["text"] == "v2"
    assert c.patch(f"/api/notes/{nid}", json={"text": "  "}).status_code == 400
    assert c.patch("/api/notes/nope", json={"text": "x"}).status_code == 404
    assert ns.list()[0].text == "v2"


# ---------------------------------------------------------------- 拖動排序

def test_store_reorder_moves_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    st = NotesStore()
    a = st.add("第一張")      # 新的在前：目前順序 c, b, a
    b = st.add("第二張")
    c = st.add("第三張")
    assert [n.id for n in st.list()] == [c.id, b.id, a.id]
    assert st.reorder([a.id, c.id]) is True, "有變動要回 True"
    assert [n.id for n in st.list()] == [a.id, c.id, b.id], \
        "列出的照給定順序；沒列的（b）排後面維持相對順序"
    assert st.reorder([a.id, c.id]) is False, "沒變動＝不寫檔"
    assert st.reorder(["nope", a.id, c.id]) is False, "未知 id 忽略後仍無變動"
    st2 = NotesStore(); st2.load()
    assert [n.id for n in st2.list()] == [a.id, c.id, b.id], "排序要持久化"


def test_notes_api_reorder_endpoint_and_bump(tmp_path, monkeypatch):
    from deskbar.webserver import create_app

    class _FakeAlarms:
        def list(self):
            return []

    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    ns = NotesStore()
    ids = [ns.add(f"n{i}").id for i in range(3)]     # list() = 反序 ids[2..0]
    state = AppState()
    app = create_app(_FakeAlarms(), notes_store=ns, usage_state=state)
    app.config["TESTING"] = True
    c = app.test_client()
    seq0 = state.snapshot().seq
    r = c.post("/api/notes/reorder", json={"order": ids})     # 反轉成 add 順序
    assert r.status_code == 200
    assert [n.id for n in ns.list()] == ids
    assert state.snapshot().seq > seq0, "重排要叫醒裝置重繪（牆即時同步）"
    seq1 = state.snapshot().seq
    assert c.post("/api/notes/reorder", json={"order": ids}).status_code == 200
    assert state.snapshot().seq == seq1, "沒變動不 bump"
    assert c.post("/api/notes/reorder", json={"order": "x"}).status_code == 400
    assert c.post("/api/notes/reorder", json={"order": [1, 2]}).status_code == 400


def test_notesview_badge_second_page_numbers():
    s = _surf()
    hits = notesview.render(s, [_note(i, f"排序 {i}") for i in range(8)],
                            notesview.new_state(), AREA, NOW, 0.0, page=1)
    assert len(hits) == 2, "第二頁兩張（7、8 號徽章）照常可點"


# ---------------------------------------------------------------- 自選顏色

def test_store_patch_color_and_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    st = NotesStore()
    n = st.add("彩色便條")
    assert n.color == -1, "新便條預設自動輪色"
    c = st.patch(n.id, color=3)
    assert c.color == 3 and c.text == "彩色便條", "只改色不動文"
    t = st.patch(n.id, text="改字")
    assert t.text == "改字" and t.color == 3, "只改文要保留顏色"
    both = st.patch(n.id, text="都改", color=0)
    assert (both.text, both.color) == ("都改", 0)
    assert st.patch(n.id, color=9) is None, "色盤索引越界拒改"
    assert st.patch(n.id) is None, "什麼都沒給拒改"
    st2 = NotesStore(); st2.load()
    assert st2.list()[0].color == 0, "顏色要持久化"


def test_store_load_old_json_without_color(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "notes.json").write_text(_json.dumps(
        [{"id": "old1", "text": "舊格式", "ts": NOW.isoformat()}]),
        encoding="utf-8")
    st = NotesStore(); st.load()
    assert st.list()[0].color == -1, "舊檔沒有 color 欄位＝自動輪色，不炸"


def test_notes_api_patch_color(client):
    nid = client.post("/api/notes", json={"text": "上色"}).get_json()["id"]
    r = client.patch(f"/api/notes/{nid}", json={"color": 2})
    assert r.status_code == 200 and r.get_json()["color"] == 2
    assert client.patch(f"/api/notes/{nid}", json={"color": 9}).status_code == 400
    assert client.patch(f"/api/notes/{nid}", json={}).status_code == 400
    assert client.patch(f"/api/notes/{nid}",
                        json={"color": True}).status_code == 400
    r2 = client.patch(f"/api/notes/{nid}", json={"text": "上色改字"})
    assert r2.get_json()["color"] == 2, "改字不掉色"


def test_notesview_respects_chosen_color():
    a, b = _surf(), _surf()
    na = Note("n1", "同一張", NOW.isoformat(), 0)
    nb = Note("n1", "同一張", NOW.isoformat(), 2)
    notesview.render(a, [na], notesview.new_state(), AREA, NOW, 0.0)
    notesview.render(b, [nb], notesview.new_state(), AREA, NOW, 0.0)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB"), \
        "指定不同色盤索引要畫出不同顏色"
