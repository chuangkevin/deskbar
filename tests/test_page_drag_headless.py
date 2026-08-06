"""待辦/便條牆跟手拖曳與吸附翻頁 headless 測試。"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui.app import (App, PAGE_FLIP_RATIO, page_drag_decision,
                            page_drag_offset)
from deskbar.ui.dashboard import CENTER_SLIDE_AREA, TL_X0, TL_X1

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)


# ---------------------------------------------------------------------------
# 任務 D：純函數測試
# ---------------------------------------------------------------------------

def test_page_drag_offset_cases():
    # 有下一頁、dx=-100、width=800 → -100 (1:1)
    assert page_drag_offset(-100, 800, has_prev=True, has_next=True) == -100.0

    # 沒有下一頁、dx=-90 → -30 (阻尼 /3)
    assert page_drag_offset(-90, 800, has_prev=True, has_next=False) == -30.0

    # 沒有上一頁、dx=+90 → +30 (阻尼 /3)
    assert page_drag_offset(90, 800, has_prev=False, has_next=True) == 30.0

    # dx 超過 width → 夾在 ±width
    assert page_drag_offset(-1000, 800, has_prev=True, has_next=True) == -800.0
    assert page_drag_offset(1000, 800, has_prev=True, has_next=True) == 800.0

    # dx=0 → 0
    assert page_drag_offset(0, 800, has_prev=True, has_next=True) == 0.0


def test_page_drag_decision_cases():
    # width=800、dx=-250 (>25%)、has_next=True → +1
    assert page_drag_decision(-250, 800, has_prev=True, has_next=True) == 1

    # dx=-100 (<25%) → 0
    assert page_drag_decision(-100, 800, has_prev=True, has_next=True) == 0

    # dx=+250、has_prev=True → -1
    assert page_drag_decision(250, 800, has_prev=True, has_next=True) == -1

    # dx=-250 但 has_next=False → 0
    assert page_drag_decision(-250, 800, has_prev=True, has_next=False) == 0

    # dx=0 → 0
    assert page_drag_decision(0, 800, has_prev=True, has_next=True) == 0


# ---------------------------------------------------------------------------
# 任務 D：Headless 渲染測試
# ---------------------------------------------------------------------------

def _issue(ident):
    from deskbar.linear import LinearIssue
    return LinearIssue(identifier=f"DESK-{ident}", title=f"Task {ident}", state_name="In Progress",
                       state_type="started", state_color="#5e6ad2", priority=1,
                       due=None, project="")


def _make_app(tmp_path, monkeypatch, center_view="linear") -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    # 填充一些 linear 任務以利分頁（1 頁可容納 6 項，餵 12 項會產生第 2 頁）
    state.set_linear([_issue(i) for i in range(12)], NOW)
    settings = Settings()
    settings.center_view = center_view
    lock = threading.Lock()
    app = App(state, settings, lock, on_save=lambda s: None)
    app.view = "dashboard"
    app.logical = pygame.Surface((1920, 480))
    app.screen = app.logical
    return app


def test_render_page_drag_band_calendar_returns_early(tmp_path, monkeypatch):
    """中欄為 calendar 時，_render_page_drag_band 直接 return，不建立 _page_drag。"""
    app = _make_app(tmp_path, monkeypatch, center_view="calendar")
    app._drag_start = (TL_X0 + 100, 100)
    app._drag_last = (TL_X0 + 200, 100)

    app._render_page_drag_band()
    assert app._page_drag is None


def test_render_page_drag_band_executes_without_exception_and_restores_page(tmp_path, monkeypatch):
    """拖曳中呼叫 _render_page_drag_band 不拋例外，且離線渲染後 center_pages 必須還原。"""
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    start_x = TL_X0 + 100
    app._drag_start = (start_x, 100)
    app._drag_last = (start_x - 100, 100)  # 往左拖看下一頁

    # 執行跟手渲染
    app._render_page_drag_band()

    # 驗證 1：_page_drag 已被建立且未拋例外
    assert app._page_drag is not None
    assert app._page_drag["center"] == "linear"
    assert app._page_drag["has_next"] is True
    assert app._page_drag["neighbour"] is not None

    # 驗證 2：離線渲染鄰頁後，center_pages["linear"] 必須被還原成原值 0
    assert app.center_pages["linear"] == 0


def test_touch_up_triggers_page_settle_and_flips_page(tmp_path, monkeypatch):
    """放手且拖曳超過 25% 時，觸發 _page_settle 動畫並翻到下一頁。"""
    app = _make_app(tmp_path, monkeypatch, center_view="linear")
    app.center_pages["linear"] = 0
    start_x = TL_X0 + 300
    app._drag_start = (start_x, 100)
    # 中欄實際寬度是 CENTER_SLIDE_AREA.w（1118），門檻＝25%＝279.5px，
    # 所以拖曳量要用實際寬度算，不能寫死魔術數字（原本寫 250 以為門檻是
    # 800*0.25=200，實機上根本不到門檻、正確行為是彈回，測試因此紅掉）。
    drag_px = int(CENTER_SLIDE_AREA.w * PAGE_FLIP_RATIO) + 20
    app._drag_last = (start_x - drag_px, 100)

    # 模擬拖曳中的一幀
    app._render_page_drag_band()
    assert app._page_drag is not None

    # 放手
    app._handle_touch_up(start_x - drag_px, 100)

    # 驗證頁碼已更新成 1 且開啟 _page_settle 吸附動畫
    assert app.center_pages["linear"] == 1
    assert app._page_settle is not None
    assert app._page_settle["to"] == -app._page_drag["rect"].w

    # 驅動動畫直至結束
    app._page_settle["start"] -= 1.0  # 模擬過期 > 0.15s
    app._render_page_settle_frame(NOW)

    # 驗證動畫結束清空狀態
    assert app._page_drag is None
    assert app._page_settle is None
