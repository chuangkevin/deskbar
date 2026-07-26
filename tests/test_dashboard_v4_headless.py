"""v4 視圖層：寬度切換/模式切換/強制同步/回今天/月視圖/行程模式的 render() hits 驗證。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.models import Event
from deskbar.store import AppState
from deskbar.ui import dashboard, theme
from deskbar.viewwin import view_window

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 37, tzinfo=TZ)   # 週一


def _surf():
    return pygame.Surface((1920, 480))


def _settings_with_account():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def _state_with_event(start, end, title="會議", account="a@x.com", all_day=False):
    st = AppState()
    st.set_events(account, [Event("e1", account, "c", title, start, end, all_day, None, None)],
                 NOW)
    return st


def test_day_span_render_has_core_control_hits():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "cycle_span" in actions
    assert "cycle_view_mode" in actions
    assert "force_sync" in actions
    # 預設 day 檔且未設 anchor：不該出現回今天鈕
    assert "goto_now" not in actions


def test_syncing_state_flag_does_not_crash_and_keeps_hits():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    st.set_syncing(True)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "force_sync" in actions


def test_anchor_set_shows_goto_now():
    settings = _settings_with_account()
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    anchor = NOW - timedelta(days=1)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    actions = {h.action for h in hits}
    assert "goto_now" in actions


def test_week_span_without_anchor_still_shows_label_and_goto_now_hidden():
    settings = _settings_with_account()
    settings.view_span = "week"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    # span != day 時即使 anchor=None 也顯示標籤，但「回今天」只在 anchor 非 None 才出現
    assert "goto_now" not in actions


def test_month_span_returns_goto_day_hits():
    settings = _settings_with_account()
    settings.view_span = "month"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    goto_day_hits = [h for h in hits if h.action == "goto_day"]
    assert goto_day_hits, "月檔應回傳 goto_day hits"
    assert all(h.data is not None for h in goto_day_hits)


def test_agenda_mode_returns_open_detail_hits():
    # 行程模式新契約（2026-07-26）：只列「從現在起」的行程，故事件須在 NOW 之後
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    detail_hits = [h for h in hits if h.action == "open_detail"]
    assert detail_hits


def test_agenda_mode_empty_window_still_returns_control_hits():
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = AppState()   # 沒有任何事件
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "cycle_span" in actions and "force_sync" in actions


def test_week_span_lanes_mode_uses_weekgrid_goto_day_cells():
    """v4.1（推翻本檔原有的「週檔連續軸細色條」假設，spec 第 11 節）：span=week
    且 mode=lanes 時，河道週檔改用 weekgrid 的「帳號×日格子」——格子整格是
    goto_day 觸控目標，不再對個別行程開 open_detail hit（那是行程模式的行為，
    連續軸的舊有「事件塊」概念在週檔已經不存在了）。取代原本的
    test_week_span_renders_long_event_without_crash。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    start = NOW.replace(hour=10, minute=0)
    st = _state_with_event(start, start + timedelta(hours=6), title="很長很長的會議標題文字")
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    goto_hits = [h for h in hits if h.action == "goto_day"]
    assert len(goto_hits) == 7   # 1 帳號 × 7 天
    assert not any(h.action == "open_detail" for h in hits)


def test_week_span_lanes_mode_renders_event_title_inside_correct_cell():
    """weekgrid 取代連續軸後，行程改成格內微列文字，不再是「塊寬度夠才顯示標題」
    的連續色塊——這裡改驗證：事件所在那一天的格子內畫得出非底色像素（微列文字
    有畫出來），取代原本的 test_week_span_shows_label_when_block_wide_enough。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    start = NOW.replace(hour=18, minute=0)
    st = _state_with_event(start, start + timedelta(hours=6), title="很長很長的會議標題文字")
    surf = _surf()
    surf.fill(theme.C["bg"])
    hits = dashboard.render(surf, st.snapshot(), settings, NOW)
    cell = next(h for h in hits if h.action == "goto_day" and h.data == NOW.date())
    # 內縮 4px 避開今天欄的細框／格線邊緣像素，只看格內容才算數。
    x0, x1 = int(cell.rect.x) + 4, int(cell.rect.x + cell.rect.w) - 4
    y0, y1 = int(cell.rect.y) + 4, int(cell.rect.y + cell.rect.h) - 4
    has_ink = any(
        surf.get_at((x, y))[:3] != theme.C["bg"]
        for y in range(y0, y1) for x in range(x0, x1))
    assert has_ink, "週檔格子內應該畫出行程微列文字"


def test_month_span_does_not_emit_goto_day_for_out_of_window_days():
    """規格：月視圖資料窗口是 [今天-7, 今天+30]。NOW=2026-07-27，窗口外的
    7 月 1 日（早於 7/20）不該出現 goto_day hit——避免使用者點了一個從沒同步過、
    畫面上看起來像「這天沒事」的日子，跳過去卻只是空白（假空）。"""
    settings = _settings_with_account()
    settings.view_span = "month"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    goto_day_dates = {h.data for h in hits if h.action == "goto_day"}
    assert date(2026, 7, 1) not in goto_day_dates
    assert date(2026, 7, 27) in goto_day_dates   # 今天本身一定在窗口內


def test_agenda_mode_shows_goto_now_with_anchor():
    """v4.1（推翻 fixwave2）：行程模式改回「視窗制」，恢復跟河道共用同一套
    show_goto_now 判斷（anchor is not None 就顯示），不再有 is_agenda 特判——
    取代原本斷言「agenda 隱藏 goto_now」的 test_agenda_mode_hides_goto_now_even_with_anchor
    （見 spec 第 11 節 v4.1：「行程」也可左右滑動、離開今天顯示回到今天）。"""
    settings = _settings_with_account()
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    anchor = NOW - timedelta(days=1)
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    actions = {h.action for h in hits}
    assert "goto_now" in actions, "v4.1：行程模式設了 anchor 後應該顯示回到今天，跟河道模式一致"

    settings.view_mode = "lanes"
    hits_lanes = dashboard.render(_surf(), st.snapshot(), settings, NOW, anchor=anchor)
    assert "goto_now" in {h.action for h in hits_lanes}


def test_agenda_mode_shows_window_label_in_agenda_format():
    """v4.1（推翻 fixwave2）：行程模式恢復顯示窗口標籤，但格式跟河道週標籤不同——
    河道「7月27日–8月2日」（view_window，週一到週日 window_label 格式）；行程
    「7/27–8/2」（agenda_window 對齊週一的 7 欄，緊湊斜線格式，見 dashboard._agenda_label），
    刻意用不同格式避免使用者誤以為兩者是同一個窗口概念。取代原本斷言「agenda
    隱藏窗口標籤」的 test_agenda_mode_hides_window_label。"""
    settings = _settings_with_account()
    settings.view_span = "week"
    st = _state_with_event(NOW.replace(hour=10), NOW.replace(hour=11))

    assert dashboard._agenda_label(date(2026, 7, 27), 7) == "7/27–8/2"

    settings.view_mode = "agenda"
    surf_agenda = _surf()
    surf_agenda.fill(theme.C["bg"])
    hits = dashboard.render(surf_agenda, st.snapshot(), settings, NOW)
    assert "cycle_span" in {h.action for h in hits}   # 基本煙霧：沒有因為改動而崩潰

    win_start, win_end = view_window("week", NOW, TZ)
    topbar = dashboard._layout_topbar("week", NOW, win_start, win_end, False, True,
                                      dashboard._agenda_label(date(2026, 7, 27), 7))
    assert topbar.label_text == "7/27–8/2"
    x0, x1 = int(topbar.label_right_x - 200), int(topbar.label_right_x)
    has_ink = any(
        surf_agenda.get_at((x, y))[:3] != theme.C["bg"]
        for y in range(10, 34) for x in range(x0, x1))
    assert has_ink, "v4.1：行程模式應該畫出窗口標籤，不再是 fixwave2 的隱藏行為"


def test_agenda_mode_on_month_span_still_uses_agenda_not_month_grid():
    settings = _settings_with_account()
    settings.view_span = "month"
    settings.view_mode = "agenda"
    st = _state_with_event(NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    hits = dashboard.render(_surf(), st.snapshot(), settings, NOW)
    actions = {h.action for h in hits}
    assert "goto_day" not in actions
    assert "open_detail" in actions
