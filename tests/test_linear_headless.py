"""Linear 待辦：GraphQL 解析/排序純函式、fetch 認證頭、store 接線、
linearview 渲染契約（三階空狀態/卡片/溢出）、中欄切換鈕 dispatch。"""
from __future__ import annotations

import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar import linear
from deskbar.config import Settings
from deskbar.linear import LinearIssue
from deskbar.store import AppState
from deskbar.ui import dashboard, linearview, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 28, 10, 0, tzinfo=TZ)
AREA = dashboard.TL_AREA


def _surf():
    s = pygame.Surface((1920, 480))
    s.fill(theme.C["bg"])
    return s


def _issue(ident, prio=3, due=None, title="做事", state="In Progress",
           color="#5e6ad2", project="SARA"):
    return LinearIssue(identifier=ident, title=title, state_name=state,
                       state_type="started", state_color=color, priority=prio,
                       due=due, project=project)


# ---------------------------------------------------------------- 解析/排序

def test_parse_issues_sorts_urgent_then_due_then_none_priority_last():
    payload = {"data": {"viewer": {"assignedIssues": {"nodes": [
        {"identifier": "S-3", "title": "無優先", "priority": 0,
         "state": {"name": "Todo", "type": "unstarted", "color": "#888888"}},
        {"identifier": "S-2", "title": "高晚到期", "priority": 2, "dueDate": "2026-08-10",
         "state": {"name": "Todo", "type": "unstarted", "color": "#888888"}},
        {"identifier": "S-1", "title": "高早到期", "priority": 2, "dueDate": "2026-07-30",
         "state": {"name": "Todo", "type": "unstarted", "color": "#888888"}},
        {"identifier": "S-0", "title": "緊急", "priority": 1,
         "state": {"name": "Todo", "type": "unstarted", "color": "#888888"}},
        {"title": "沒 identifier 的壞節點"},
        "不是 dict 的垃圾",
    ]}}}}
    out = linear.parse_issues(payload)
    assert [i.identifier for i in out] == ["S-0", "S-1", "S-2", "S-3"]
    assert out[1].due == date(2026, 7, 30)


def test_parse_issues_tolerates_empty_and_malformed_payload():
    assert linear.parse_issues({}) == []
    assert linear.parse_issues({"data": None}) == []
    assert linear.parse_issues(None) == []


def test_state_rgb_parses_hex_and_falls_back():
    assert linear.state_rgb("#5e6ad2") == (94, 106, 210)
    assert linear.state_rgb("5e6ad2") == (94, 106, 210)
    for bad in ("", None, "#xyz", "#12"):
        assert linear.state_rgb(bad) == (140, 146, 164)


def test_fetch_issues_uses_raw_key_auth_and_raises_on_gql_errors():
    calls = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"errors": [{"message": "bad key"}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.update(url=url, headers=headers)
        return _Resp()

    with pytest.raises(RuntimeError):
        linear.fetch_issues("lin_api_XXX", http_post=fake_post)
    assert calls["url"] == linear.GQL_URL
    assert calls["headers"]["Authorization"] == "lin_api_XXX", "個人金鑰不加 Bearer"


# ---------------------------------------------------------------- store

def test_store_set_linear_bumps_seq_and_snapshots():
    st = AppState()
    seq0 = st.snapshot().seq
    st.set_linear([_issue("S-1")], NOW)
    snap = st.snapshot()
    assert snap.seq > seq0
    assert [i.identifier for i in snap.linear] == ["S-1"]
    assert snap.linear_at == NOW


# ---------------------------------------------------------------- linearview

def test_linearview_hint_when_no_key():
    st = AppState()
    s = _surf()
    base = pygame.image.tobytes(s, "RGB")
    linearview.render(s, st.snapshot(), Settings(), AREA, NOW)
    assert pygame.image.tobytes(s, "RGB") != base, "沒 Key 要畫指引文字"


def test_linearview_syncing_then_empty_states():
    settings = Settings()
    settings.linear_api_key = "k"
    st = AppState()
    a = _surf()
    linearview.render(a, st.snapshot(), settings, AREA, NOW)     # 未同步過
    st.set_linear([], NOW)
    b = _surf()
    linearview.render(b, st.snapshot(), settings, AREA, NOW)     # 同步過但空
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB")


def test_linearview_renders_cards_and_overflow():
    settings = Settings()
    settings.linear_api_key = "k"
    st = AppState()
    st.set_linear([_issue(f"S-{i}", prio=2, due=date(2026, 7, 27) if i == 0 else None,
                          title=f"待辦事項 {i}") for i in range(10)], NOW)
    s = _surf()
    linearview.render(s, st.snapshot(), settings, AREA, NOW)
    blank = _surf()
    assert pygame.image.tobytes(s, "RGB") != pygame.image.tobytes(blank, "RGB")
    # 溢出標示（10 件只畫 8 件）
    strip = s.subsurface(pygame.Rect(AREA.x + AREA.w - 120, AREA.y + AREA.h,
                                     120, 480 - AREA.y - AREA.h))
    assert pygame.image.tobytes(strip, "RGB") != \
        pygame.image.tobytes(blank.subsurface(strip.get_rect(
            topleft=(AREA.x + AREA.w - 120, AREA.y + AREA.h))), "RGB"), \
        "＋N 件溢出標示應該存在"


# ---------------------------------------------------------------- 切換鈕

def test_dashboard_linear_mode_swaps_topbar_buttons():
    settings = Settings()
    settings.linear_api_key = "k"
    st = AppState()
    st.set_linear([_issue("S-1")], NOW)
    hits_cal = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    acts_cal = {h.action for h in hits_cal}
    assert {"toggle_center", "cycle_span", "cycle_view_mode"} <= acts_cal
    settings.center_view = "linear"
    hits_lin = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    acts_lin = {h.action for h in hits_lin}
    assert "toggle_center" in acts_lin
    assert "cycle_span" not in acts_lin and "cycle_view_mode" not in acts_lin, \
        "待辦模式不該出現行事曆專屬按鈕"


def test_toggle_center_dispatch_flips_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    saved = []
    app = App(AppState(), Settings(), threading.Lock(),
              on_save=lambda s: saved.append(1), alarm_store=None)
    app.view = "dashboard"
    app.hits = dashboard.render(_surf(), app.state.snapshot(), app.settings, NOW)
    hit = next(h for h in app.hits if h.action == "toggle_center")
    seen = []
    for _ in range(3):
        app._dispatch(hit.rect.x + 2, hit.rect.y + 2)
        seen.append(app.settings.center_view)
    assert seen == ["linear", "notes", "calendar"], "三態循環：行事曆→待辦→便條→行事曆"
    assert saved