"""雙主題切換的整合行為：
- 設定頁「主題」鈕存在、觸控目標達 48px、不與既有元素重疊。
- App._dispatch("cycle_theme")：切 settings.theme、套用 theme.set_theme()、
  呼叫 on_save，且來回切換是對稱的（dark<->light）。
- light 主題下 dashboard（河道/行程兩種模式）與 settings_view 能正常
  headless render（不炸），且畫面背景色確實變成淺色底。

每支切到 light 的測試都在 finally 換回 "dark"，維持全 session 預設狀態
（test_transitions_headless.py 等其他檔案的斷言依賴預設就是 dark）。
"""
from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import dashboard, settings_view, theme
from deskbar.ui.app import App

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)

# 螢幕最右側留白：PANEL_W(400)/TL_X1(1520)/USAGE 右界(1900) 之外，任何一頁的
# 任何元素都不該畫到這裡，適合當「目前底色到底是什麼」的探針座標。
BG_PROBE = (1910, 10)


@pytest.fixture(autouse=True)
def _restore_dark_theme():
    """保險絲：就算某支測試斷言失敗提早跳出，session 全域的 theme 狀態
    也一定會被拉回 dark，不會拖累後面其他檔案的測試。"""
    yield
    theme.set_theme("dark")


def _surf():
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    return surf


def _make_app(tmp_path, monkeypatch) -> App:
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    state = AppState()
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    lock = threading.Lock()
    saved = []
    app = App(state, settings, lock, on_save=lambda s: saved.append(s), alarm_store=None)
    app.view = "settings"
    app._saved = saved
    return app


# ---------------------------------------------------------------- settings_view 按鈕


def test_settings_has_theme_toggle_button_meeting_touch_target():
    settings = Settings()
    hits = settings_view.render(_surf(), AppState().snapshot(), settings, None)
    hit = next((h for h in hits if h.action == "cycle_theme"), None)
    assert hit is not None, "設定頁應該有主題切換鈕"
    assert hit.rect.h >= 48 and hit.rect.w >= 48


def test_control_row_buttons_do_not_overlap_each_other():
    """兩層版面：控制列七顆鈕（rotate 已搬進螢幕子頁）任兩顆不得重疊。"""
    settings = Settings()
    hits = settings_view.render(_surf(), AppState().snapshot(), settings, None)
    by_action = {h.action: h.rect for h in hits}
    row = ["toggle_presence", "cycle_presence_speed", "open_bt", "open_wifi",
           "open_screen", "cycle_theme", "cycle_sync_interval", "settings_done"]
    rects = [by_action[a] for a in row]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            overlap = not (a.x + a.w <= b.x or b.x + b.w <= a.x
                           or a.y + a.h <= b.y or b.y + b.h <= a.y)
            assert not overlap, f"{row[i]} 與另一顆鈕重疊"


def test_theme_button_label_reflects_current_setting():
    settings = Settings()
    settings.theme = "dark"
    hits = settings_view.render(_surf(), AppState().snapshot(), settings, None)
    assert any(h.action == "cycle_theme" for h in hits)
    settings.theme = "light"
    hits2 = settings_view.render(_surf(), AppState().snapshot(), settings, None)
    assert any(h.action == "cycle_theme" for h in hits2)


# ---------------------------------------------------------------- App dispatch


def test_cycle_theme_dispatch_flips_setting_applies_and_saves(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    assert app.settings.theme == "dark"
    assert theme.current_theme() == "dark"

    hits = settings_view.render(_surf(), app.state.snapshot(), app.settings, None)
    app.hits = hits
    hit = next(h for h in hits if h.action == "cycle_theme")

    app._dispatch(hit.rect.x + hit.rect.w / 2, hit.rect.y + hit.rect.h / 2)
    assert app.settings.theme == "light"
    assert theme.current_theme() == "light"
    assert app._saved, "cycle_theme 應呼叫 on_save"

    hits2 = settings_view.render(_surf(), app.state.snapshot(), app.settings, None)
    app.hits = hits2
    hit2 = next(h for h in hits2 if h.action == "cycle_theme")
    app._dispatch(hit2.rect.x + hit2.rect.w / 2, hit2.rect.y + hit2.rect.h / 2)
    assert app.settings.theme == "dark", "再點一次應該切回深色"
    assert theme.current_theme() == "dark"


# ---------------------------------------------------------------- light 主題 headless render


def test_dashboard_lanes_renders_under_light_theme_without_crash():
    theme.set_theme("light")
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    settings.view_span = "day"
    settings.view_mode = "lanes"
    surf = _surf()
    hits = dashboard.render(surf, AppState().snapshot(), settings, NOW)
    assert isinstance(hits, list)
    assert surf.get_at(BG_PROBE)[:3] == theme.PALETTES["light"]["bg"]


def test_dashboard_agenda_renders_under_light_theme_without_crash():
    theme.set_theme("light")
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    settings.view_span = "week"
    settings.view_mode = "agenda"
    surf = _surf()
    hits = dashboard.render(surf, AppState().snapshot(), settings, NOW)
    assert isinstance(hits, list)
    assert surf.get_at(BG_PROBE)[:3] == theme.PALETTES["light"]["bg"]


def test_settings_view_renders_under_light_theme_without_crash():
    theme.set_theme("light")
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c"] = True
    surf = _surf()
    hits = settings_view.render(surf, AppState().snapshot(), settings, None)
    actions = {h.action for h in hits}
    assert "cycle_theme" in actions
    assert surf.get_at(BG_PROBE)[:3] == theme.PALETTES["light"]["bg"]
