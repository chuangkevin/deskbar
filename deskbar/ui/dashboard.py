from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time as _time, timedelta

import pygame

from deskbar.layout import Rect, layout_timeline_range, split_allday, time_to_x_range
from deskbar.ui import Hit
from deskbar.ui import agenda, eventcard, icons, monthgrid, theme, transitions, usagewidget, weekgrid
from deskbar.viewwin import agenda_window, data_window, view_window, window_label
from deskbar.weather import code_text

# 三欄版面（2026-07 三欄重構）：左＝時鐘/日期/天氣/同步狀態，中＝行事曆時間軸，
# 右＝Claude usage 油表。座標全部集中在這裡，其餘子渲染（agenda/weekgrid/monthgrid/
# grid_range/now_line/lanes）一律吃 TL_AREA 或 module 常量，不再各自硬寫魔術數字。
PANEL_W, TL_X0, TL_X1 = 400, 420, 1520
TL_AREA = Rect(TL_X0, 52, TL_X1 - TL_X0, 368)
USAGE_X0, USAGE_W = 1540, 360            # 右欄 1540..1900：跟左/中欄一樣在螢幕右緣留 20px
SPAN_LABELS = {"half": "半天", "day": "日", "week": "週", "month": "月"}
# 寬度鈕／模式鈕改放中欄頂帶右側（原本在畫面最右側，現在中欄變窄，兩顆鈕改貼中欄右界，
# 右欄完全不放任何頂帶元素）。
SPAN_BTN = Rect(1290, 2, 110, 48)
MODE_BTN = Rect(1408, 2, 110, 48)
CENTER_BTN = Rect(1172, 2, 110, 48)      # 行事曆↔待辦（Linear）切換
WORK_BTN = Rect(1034, 2, 130, 48)        # 頂列工作 Session 直達鈕
GOTO_NOW_W, GOTO_NOW_H = 110, 40        # 「回到今天」鈕：緊貼工作直達鈕左側
TOPBAR_GAP = 16                          # 頂帶固定區塊之間的最小留白
# 中欄內容的滑動過場區域：x 避開左欄分隔線(400)與右界線(1520)，y 從頂帶以下開始
# ——過場只滑「內容」，左右欄與頂列按鈕是 chrome，釘死不動（2026-07-30 實機回報）。
CENTER_SLIDE_AREA = Rect(PANEL_W + 2, 52, TL_X1 - PANEL_W - 2, 480 - 52)
# 2026-07-27：頂欄整日行程膠囊（_render_allday／_layout_allday_chips）已移除——
# 整日事件已在 agenda 模式的日欄與 weekgrid 的格子內顯示徽章，頂帶空間讓給窗口
# 標籤／按鈕。迫近脈動（imminent_events/_pulse_t/_pulse_color）改用
# deskbar.ui.transitions 的等價實作（imminent_ids/pulse_border_color），這裡不再
# 重複一份。


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.text_surface(s, size, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _chip_btn(surface, label, rect: Rect, action, hits, size=22):
    r = pygame.Rect(int(rect.x), int(rect.y), int(rect.w), int(rect.h))
    pygame.draw.rect(surface, theme.C["card"], r, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=8)
    img = theme.text_surface(label, size, theme.C["text"])
    surface.blit(img, img.get_rect(center=r.center))
    hits.append(Hit(rect, action, None))


@dataclass(frozen=True)
class TopbarLayout:
    """頂帶（y=0..50）版面計算結果。從右到左固定保留：模式鈕(MODE_BTN)、寬度鈕
    (SPAN_BTN)——這兩顆位置永遠不變，直接用模組常量；「回到今天」鈕與窗口標籤是否
    出現視 anchor／span 而定，位置由這支統一算出，避免各自各算、互相畫到對方頭上。"""
    goto_now_rect: Rect | None      # None＝這一幀不畫「回到今天」
    label_text: str                 # 空字串＝這一幀不畫窗口標籤
    label_right_x: float            # 標籤右對齊基準 x（label_text 為空時無意義）
    chip_right_x: float             # 整日 chips／溢出小字最多只能畫到這個 x


def _layout_topbar(span, anchor_or_now, win_start, win_end,
                   show_goto_now: bool, show_label: bool,
                   label_override: str | None = None) -> TopbarLayout:
    """純函數：只算幾何，不畫、不動 surface。回到今天鈕寬 110，緊貼寬度鈕左側
    （右邊界＝SPAN_BTN.x，中間不留縫）；窗口標籤右對齊到「回到今天鈕或寬度鈕，
    取較左者」的左側再減 16px 留白；整日 chips 的可用右界＝以上所有「這一幀有出現」
    的元素中最靠左的 x，再減 16px。任何資料量／任何標籤長度下，四者之間必定
    保有 >=16px 間隔，不會互相重疊。

    label_override：非 None 時直接採用這段文字（行程模式用，見 _agenda_label），
    不呼叫 window_label——行程模式的視窗是 agenda_window 算出的日期範圍，跟河道
    的 view_window 不是同一組數字，標籤格式也不同（"7/27–8/2" vs "7月27日–8月2日"）。
    """
    # 2026-07-30：CENTER_BTN（中欄切換）固定佔 1172..1282，「回到今天」再往左
    # 一格——首日把它留在 SPAN_BTN 左側，跟切換鈕整顆重疊（實機滑動時回報）。
    goto_now_rect = (Rect(WORK_BTN.x - GOTO_NOW_W, 4, GOTO_NOW_W, GOTO_NOW_H)
                     if show_goto_now else None)
    leftmost = goto_now_rect.x if goto_now_rect is not None else WORK_BTN.x

    label_text = ""
    label_right_x = leftmost - TOPBAR_GAP
    if show_label:
        label_text = (label_override if label_override is not None
                     else window_label(span, anchor_or_now, win_start, win_end))
        label_w = theme.font(22).size(label_text)[0]
        leftmost = label_right_x - label_w

    chip_right_x = leftmost - TOPBAR_GAP
    return TopbarLayout(goto_now_rect, label_text, label_right_x, chip_right_x)


def _agenda_label(start_date, n_days: int) -> str:
    """行程模式窗口標籤：單欄「7月27日」；多欄（週/月，7 欄）「7/27–8/2」。
    格式故意跟河道的 window_label 不同——這裡標的是 agenda_window 實際鋪出來的
    日期範圍，用緊湊的斜線格式跟河道週標籤（「N月N日–N月N日」）區分開，避免使用者
    誤以為兩者是同一個窗口概念。"""
    if n_days <= 1:
        return f"{start_date.month}月{start_date.day}日"
    end_date = start_date + timedelta(days=n_days - 1)
    return f"{start_date.month}/{start_date.day}–{end_date.month}/{end_date.day}"


def render(surface, snap, settings, now: datetime, clock_anim=None, anchor=None,
          weather_t=0.0, notes_store=None, notes_ui=None,
          linear_page=0, notes_page=0, sedentary=False,
          scene_ui=None) -> list[Hit]:
    hits: list[Hit] = []
    tz = now.tzinfo
    span = settings.view_span
    anchor_or_now = anchor if anchor is not None else now
    win_start, win_end = view_window(span, anchor_or_now, tz,
                                     start_hour=settings.start_hour, end_hour=settings.end_hour)

    _render_panel(surface, snap, settings, now, hits, clock_anim, weather_t,
                  sedentary)
    pygame.draw.line(surface, theme.C["panel_line"], (PANEL_W, 0), (PANEL_W, 480))
    pygame.draw.line(surface, theme.C["panel_line"], (TL_X1, 0), (TL_X1, 480))

    # 中欄五態循環：行事曆 → 待辦（Linear）→ 便條 → 工作 Sessions → 場景。
    # 頂列工作 Session 直達鈕永遠顯示於頂帶。
    center = getattr(settings, "center_view", "calendar")
    next_label = {"calendar": "待辦", "linear": "便條", "notes": "工作",
                  "sessions": "場景", "scene": "行事曆"}
    active_cnt = len(snap.work_sessions.active_items(now)) if (snap and hasattr(snap, "work_sessions") and snap.work_sessions) else 0
    unread_res_cnt = snap.work_sessions.unread_result_count(now) if (snap and hasattr(snap, "work_sessions") and snap.work_sessions) else 0
    unread_tot_cnt = snap.work_sessions.unread_count(now) if (snap and hasattr(snap, "work_sessions") and snap.work_sessions) else 0
    if unread_res_cnt > 0:
        work_label = f"工作 {active_cnt} · {unread_res_cnt}結果"
    elif unread_tot_cnt > 0:
        work_label = f"工作 {active_cnt} · {unread_tot_cnt}新"
    else:
        work_label = f"工作 {active_cnt}"

    if center != "scene":
        _chip_btn(surface, next_label.get(center, "待辦"), CENTER_BTN,
                  "toggle_center", hits)
        _chip_btn(surface, work_label, WORK_BTN, "open_work_sessions", hits, size=20)

    if center == "linear":
        from deskbar.ui import linearview
        _text(surface, "待辦事項", 22, theme.C["text2"], TL_X0, 22)
        hits += linearview.render(surface, snap, settings, TL_AREA, now,
                                  page=linear_page)
        usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W,
                           settings.usage_sources, getattr(settings, "oa_aliases", {}))
        _render_right_lower(surface, snap, now, hits, todo_fallback=False)
        return _finish(surface, snap, settings, now, hits)   # 中欄即完整待辦牆，右欄摘要免了
    if center == "notes":
        from deskbar.ui import notesview
        _text(surface, "便條", 22, theme.C["text2"], TL_X0, 22)
        notes = notes_store.list() if notes_store is not None else []
        import time as _t
        hits += notesview.render(surface, notes, notes_ui or notesview.new_state(),
                                 TL_AREA, now, _t.monotonic(), page=notes_page)
        usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W,
                           settings.usage_sources, getattr(settings, "oa_aliases", {}))
        _render_right_lower(surface, snap, now, hits)
        return _finish(surface, snap, settings, now, hits)
    if center == "sessions":
        from deskbar.ui import worksessionwidget
        working_cnt = sum(1 for item in snap.work_sessions.active_items(now) if item.activity_state == "working") if (snap and hasattr(snap, "work_sessions") and snap.work_sessions) else 0
        header_parts = ["工作台", f"活躍 {active_cnt}"]
        if unread_res_cnt > 0:
            header_parts.append(f"結果待看 {unread_res_cnt}")
        if working_cnt > 0:
            header_parts.append(f"執行中 {working_cnt}")
        _text(surface, " · ".join(header_parts), 22, theme.C["text2"], TL_X0, 22)
        hits += worksessionwidget.render_center_view(surface, snap, settings, TL_AREA, now)
        usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W,
                           settings.usage_sources, getattr(settings, "oa_aliases", {}))
        _render_right_lower(surface, snap, now, hits)
        return _finish(surface, snap, settings, now, hits)
    if center == "scene":
        from deskbar.ui import scenes
        hits += scenes.render(surface, scene_ui if scene_ui is not None
                              else scenes.new_state(), now, weather_t,
                              enabled=getattr(settings, "scenes_enabled", None),
                              weather_code=snap.weather.code
                              if snap.weather else None)
        # 場景會鋪滿中欄；控制鈕要在場景之後重畫，否則視覺上無法進入工作頁。
        _chip_btn(surface, next_label.get(center, "待辦"), CENTER_BTN,
                  "toggle_center", hits)
        _chip_btn(surface, work_label, WORK_BTN, "open_work_sessions", hits, size=20)
        usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W,
                           settings.usage_sources, getattr(settings, "oa_aliases", {}))
        _render_right_lower(surface, snap, now, hits)
        return _finish(surface, snap, settings, now, hits)

    lane_emails = [e for e in settings.accounts if settings.accounts[e].calendars] \
        or list(snap.statuses)
    if settings.presence_enabled and settings.presence_hide_accounts \
            and not snap.presence.present:
        hidden = set(settings.presence_hide_accounts)
        lane_emails = [e for e in lane_emails if e not in hidden]
    visible = [e for e in snap.events
               if e.account in lane_emails and e.end > win_start and e.start < win_end]
    allday, timed = split_allday(visible)

    # v4.1：行程模式改回「視窗制」（跟河道共用 anchor／資料窗口概念），故窗口標籤
    # 與「回到今天」鈕的顯示條件不再依 is_agenda 特判——回到 fixwave2 之前、
    # is_agenda 尚未存在時的原始公式；label 文字本身在 agenda 模式另外覆寫成
    # agenda_window 對應的格式（見下方 label_override）。
    is_agenda = settings.view_mode == "agenda"
    show_goto_now = anchor is not None
    show_label = anchor is not None or span != "day"

    agenda_start = agenda_days = None
    label_override = None
    if is_agenda:
        agenda_start, agenda_days = agenda_window(span, anchor_or_now, tz)
        label_override = _agenda_label(agenda_start, agenda_days)

    topbar = _layout_topbar(span, anchor_or_now, win_start, win_end, show_goto_now, show_label,
                            label_override)

    _render_span_mode_buttons(surface, settings, hits)
    if topbar.goto_now_rect is not None:
        _chip_btn(surface, "回到今天", topbar.goto_now_rect, "goto_now", hits, size=20)
    if topbar.label_text:
        _text(surface, topbar.label_text, 22, theme.C["text2"],
             topbar.label_right_x, 22, "midright")

    if is_agenda:
        a_win_start = datetime.combine(agenda_start, _time(0, 0), tzinfo=tz)
        a_win_end = a_win_start + timedelta(days=agenda_days)
        agenda_events = [e for e in snap.events
                         if e.account in lane_emails and e.end > a_win_start
                         and e.start < a_win_end]
        hits += agenda.render_agenda(surface, agenda_events, settings, agenda_start,
                                     agenda_days, now, tz, TL_AREA)
    elif span == "month":
        hits += monthgrid.render_month(surface, visible, lane_emails, settings, win_start,
                                       TL_AREA, now)
    elif span == "week":
        hits += weekgrid.render_week(surface, visible, lane_emails, settings, win_start.date(),
                                     now, tz, TL_AREA)
    else:
        _render_grid_range(surface, win_start, win_end)
        _render_data_window_overlay(surface, win_start, win_end, now, tz)
        allday_accounts = {e.account for e in allday}
        placed, overflow = layout_timeline_range(timed, lane_emails, win_start,
                                                 win_end, TL_AREA,
                                                 allday_accounts=allday_accounts)
        _render_lanes(surface, lane_emails, settings)
        imminent_evt_ids = transitions.imminent_ids(timed, now)
        for p in placed:
            main, _dark = theme.account_color(settings.accounts[p.event.account].color)
            r = pygame.Rect(int(p.rect.x), int(p.rect.y) + 2, int(p.rect.w), int(p.rect.h) - 4)
            label = ("◀ " if p.clip_l else "") + p.event.title + (" ▶" if p.clip_r else "")
            time_text = (f"{p.event.start.strftime('%H:%M')} – "
                         f"{p.event.end.strftime('%H:%M')}")
            pulse = (transitions.pulse_border_color(main, now)
                     if p.event.id in imminent_evt_ids else None)
            eventcard.draw_card(surface, r, main, label, time_text, pulse_color=pulse)
            hits.append(Hit(p.rect, "open_detail", p.event))
        if overflow:
            _text(surface, f"＋{len(overflow)} 更多", 20, theme.C["muted"], TL_X1, 44, "topright")
        _render_allday_pills(surface, allday, lane_emails, settings, hits)
        _render_now_line_range(surface, win_start, win_end, now)

    # 在場感應不畫任何角落圖示（2026-07-27 首日 UAT：右上鎖頭被誤認為異常
    # 狀態，使用者要求移除——隱私簾的「效果」本身就是狀態指示）。
    # 右欄：Claude usage 油表——獨立呼叫，不吃 TL_AREA、不產生 hits（純資訊面板，
    # 跟左欄時鐘/天氣一樣不可互動），畫在最後純粹是慣例（跟中欄內容互不重疊，順序無關）。
    usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W,
                       settings.usage_sources, getattr(settings, "oa_aliases", {}))
    _render_right_lower(surface, snap, now, hits)
    return _finish(surface, snap, settings, now, hits)


def _finish(surface, snap, settings, now, hits) -> list:
    """所有 return 前的共同收尾：頂緣日光帶（overlay 蓋在三欄之上）。
    日出日落用天氣快照的 open-meteo 真值，沒有才退天文計算（sunstrip._resolve）。"""
    from deskbar.ui import sunstrip
    w = snap.weather
    sunstrip.draw(surface, now, settings.weather_lat, settings.weather_lon,
                  rise=getattr(w, "sunrise", None) if w else None,
                  sset=getattr(w, "sunset", None) if w else None)
    return hits


def _render_right_todo_mini(surface, snap, now) -> None:
    """右欄下半（油表最深畫到 y≈352，其下原本整片留白）：前 3 件待辦摘要。
    行事曆/便條視圖也能瞄到最重要的事，不必切到待辦視圖。"""
    if snap.linear:
        from deskbar.ui import linearview
        linearview.render_mini(surface, snap, USAGE_X0, 362, USAGE_W, now)


def _render_right_lower(surface, snap, now, hits, *, todo_fallback: bool = True) -> None:
    """右欄下半：顯示待辦摘要。"""
    if todo_fallback:
        _render_right_todo_mini(surface, snap, now)


def _render_right_work_sessions(surface, snap, now, hits) -> None:
    """右欄工作 Session 摘要：僅在有資料且 strictly < 30m 時出現。"""
    from deskbar.ui import worksessionwidget
    ws_hits, _ = worksessionwidget.render_summary(
        surface, snap, now, USAGE_X0, 362, USAGE_W, max_rows=3)
    hits.extend(ws_hits)


def render_panel_only(surface, snap, settings, now, weather_t=0.0,
                      sedentary=False) -> None:
    """氛圍幀專用（app._render_ambient）：只重畫左欄矩形（0..PANEL_W），中欄/右欄
    的像素一概不碰——資料沒變時天氣場景逐幀動起來，不需要重算整面行事曆。
    hits 丟棄：左欄可點區塊（時鐘/同步/齒輪）的位置是常量，沿用上次全量重繪
    的結果即可。PANEL_W 分隔線畫在 x=PANEL_W、fill 只蓋到 x=PANEL_W-1，不會擦掉。"""
    surface.fill(theme.C["bg"], pygame.Rect(0, 0, PANEL_W, 480))
    _render_panel(surface, snap, settings, now, [], None, weather_t,
                  sedentary)
    _finish(surface, snap, settings, now, [])


def _render_panel(surface, snap, settings, now, hits, clock_anim=None,
                  weather_t=0.0, sedentary=False):
    """左欄（0..PANEL_W=400）：時鐘/日期/天氣/同步狀態。三欄重構把這欄從 480 縮到
    400px，時鐘改用 digit_h=96（4 卡+冒號實測總寬 342px，遠低於 360 的安全上限），
    其餘文字/圖示座標跟著往內收，確保沒有任何元素畫出 PANEL_W 之外。"""
    w = snap.weather
    if w is not None:
        from deskbar.ui import weatherfx
        night = not (6 <= now.hour < 19)   # 19:00–05:59 視為夜間：晴/多雲改月亮星空
        weatherfx.draw(surface, w.code, weather_t, w=PANEL_W, night=night,
                       clouds=False, celestial=False)   # 雲與日月全由 sensewx
                                                        # 中央徽章負責
        from deskbar.ui import sensewx
        # 天體位置不變，但物理上在實體翻牌卡後方；卡片負責正確遮蔽。
        sensewx.draw_celestial(surface, w.code, weather_t, night)
    anim = clock_anim if clock_anim else (now.strftime("%H:%M"), 1.0)
    from deskbar.ui import flipclock
    flipclock.draw(surface, 42, 34, now.strftime("%H:%M"), anim[0], anim[1],
                   digit_h=96)    # 4 卡＋中央空隙共 316px，正好置中 PANEL_W=400
    if w is not None:
        # Sense 近景天氣層：雲霧在卡片前方，日/月已在卡片後方完成。
        night = not (6 <= now.hour < 19)
        sensewx.draw_foreground(surface, w.code, weather_t, night)
        sensewx.draw_info(surface, w, now)
    wd = "週" + "一二三四五六日"[now.weekday()]
    img = theme.text_surface(f"{now.month}月{now.day}日 {wd}", 24, theme.C["text2"], bold=True)
    surface.blit(img, (24, 150))
    _render_next_event(surface, snap, settings, now)
    if snap.syncing:
        msg = "同步中…"
        dot = theme.C["now"]
    else:
        ok = all(s.ok for s in snap.statuses.values()) if snap.statuses else True
        ages = [s.last_sync for s in snap.statuses.values() if s.last_sync]
        if ages:
            mins = int((now - max(ages)).total_seconds() // 60)
            msg = f"已同步 {mins} 分鐘前" if ok else "部分帳號同步異常"
        else:
            msg = "等待首次同步"
        dot = theme.C["ok"] if ok else theme.C["warn"]
    if sedentary:
        # 久坐提示：一行安靜的字，3 分鐘後自己消失（SedentaryTracker 控時）。
        # 不彈窗不變色——這塊螢幕在辦公室，提示只該給坐在它前面的人看見。
        _text(surface, "坐滿一小時了，起來動一動", 18, theme.C["text2"], 24, 404)
    pygame.draw.circle(surface, dot, (32, 449), 5)
    _text(surface, msg, 18, theme.C["muted"], 46, 440)
    hits.append(Hit(Rect(20, 26, 370, 130), "open_alarms", None))
    hits.append(Hit(Rect(20, 424, 290, 48), "force_sync", None))    # 左下同步狀態＝點擊強制同步
    gear = Rect(320, 396, 72, 72)
    icons.draw_gear(surface, 352, 432, 18, theme.C["muted"])
    hits.append(Hit(gear, "open_settings", None))
    if w is not None:
        from deskbar.ui import weatherfx
        # 玻璃前景：蓋在左欄「全部內容」之上（含時鐘）——HTC Sense 的螢幕就是
        # 一片擋風玻璃，雨滴黏在玻璃上、雨刷從時鐘前面刷過去。
        weatherfx.draw_glass(surface, w.code, weather_t, w=PANEL_W)


def _visible_lane_emails(snap, settings) -> list:
    """render() 中欄泳道帳號篩選的同一套規則（含在場感應隱私簾），抽出來給
    左欄倒數與自動切換共用——「下一個行程」永遠跟畫面上看得到的行程一致。"""
    lane_emails = [e for e in settings.accounts if settings.accounts[e].calendars] \
        or list(snap.statuses)
    if settings.presence_enabled and settings.presence_hide_accounts \
            and not snap.presence.present:
        hidden = set(settings.presence_hide_accounts)
        lane_emails = [e for e in lane_emails if e not in hidden]
    return lane_emails


def next_event(snap, settings, now):
    """今天接下來最早開始的計時行程（尊重隱私簾），沒有回 None。"""
    emails = set(_visible_lane_emails(snap, settings))
    best = None
    for e in snap.events:
        if e.account not in emails or e.all_day:
            continue
        if e.start <= now or e.start.astimezone(now.tzinfo).date() != now.date():
            continue
        if best is None or e.start < best.start:
            best = e
    return best


def _render_next_event(surface, snap, settings, now) -> None:
    """左欄「下一個行程」倒數（y=272..330，天氣行之下、同步狀態之上）：
    比整條時間軸更常被瞄的一行字——Apple Watch complication 的概念。
    畫在 _render_panel 內＝氛圍幀逐幀跟著重畫，倒數分鐘數永遠是活的。"""
    ev = next_event(snap, settings, now)
    if ev is None:
        return
    mins = int((ev.start - now).total_seconds() // 60)
    cd = f"{mins} 分鐘後" if mins < 60 else f"{mins // 60} 小時 {mins % 60:02d} 分後"
    imminent = mins <= 15
    r = _text(surface, "接下來", 16, theme.C["muted"], 24, 272)
    img = theme.text_surface(cd, 16, theme.C["now"] if imminent
                                           else theme.C["text2"], bold=True)
    surface.blit(img, (r.right + 12, 272))
    title = theme.truncate_to_width(f"{ev.start.strftime('%H:%M')} {ev.title}",
                                    theme.font(22, weight="medium"), PANEL_W - 48)
    img = theme.text_surface(title, 22, theme.C["text"], weight="medium")
    surface.blit(img, (24, 296))


def _render_span_mode_buttons(surface, settings, hits):
    _chip_btn(surface, SPAN_LABELS.get(settings.view_span, settings.view_span),
             SPAN_BTN, "cycle_span", hits)
    _chip_btn(surface, "行程" if settings.view_mode == "agenda" else "河道",
             MODE_BTN, "cycle_view_mode", hits)


def _render_grid_range(surface, win_start, win_end):
    """half / day 專用（v4.1 起 week 改走 weekgrid，不再共用這支）：每 2 小時
    整點畫一條淡格線＋時刻標籤。時刻標籤用「midtop」置中在格線上，但兩端的
    格線可能剛好落在 TL_X0/TL_X1 邊界上（例如 win_end=24:00）——置中錨點不夾住
    的話，文字會有半個字寬畫出中欄邊界外（縮窄成 1100px 中欄後，這幾像素就
    緊貼著跟右欄之間僅 20px 的留白，值得夾住避免溢出）。格線本身仍畫在真實
    時間位置，只有文字錨點夾在 [TL_X0, TL_X1] 內。"""
    t = win_start.replace(minute=0, second=0, microsecond=0)
    if t < win_start:
        t += timedelta(hours=1)
    while t <= win_end:
        if t.hour % 2 == 0:
            x = time_to_x_range(t, win_start, win_end, TL_X0, TL_X1)
            pygame.draw.line(surface, theme.C["grid"], (x, 52), (x, 420))
            label = f"{t.hour:02d}"
            half_w = theme.font(20).size(label)[0] / 2
            label_x = min(max(x, TL_X0 + half_w), TL_X1 - half_w)
            _text(surface, label, 20, theme.C["muted"], label_x, 434, "midtop")
        t += timedelta(hours=1)


def _render_data_window_overlay(surface, win_start, win_end, now, tz) -> None:
    """半天/日/週連續軸視圖：若可視窗口有一段落在「已同步資料窗口」之外，
    在那段 x 範圍蓋一層暗色帶＋一次「未同步範圍」提示，避免把「還沒同步」畫成「真的沒事」。"""
    dw_start, dw_end = data_window(now.date(), tz)
    segments = []
    if win_start < dw_start:
        segments.append((win_start, min(win_end, dw_start)))
    if win_end > dw_end:
        segments.append((max(win_start, dw_end), win_end))
    labeled = False
    for seg_start, seg_end in segments:
        if seg_end <= seg_start:
            continue
        x0 = time_to_x_range(seg_start, win_start, win_end, TL_X0, TL_X1)
        x1 = time_to_x_range(seg_end, win_start, win_end, TL_X0, TL_X1)
        w = max(1, round(x1 - x0))
        band = pygame.Surface((w, TL_AREA.h), pygame.SRCALPHA)
        band.fill((*theme.C["dim_band"], 170))
        surface.blit(band, (round(x0), TL_AREA.y))
        if not labeled:
            _text(surface, "未同步範圍", 20, theme.C["muted"],
                 (x0 + x1) / 2, TL_AREA.y + TL_AREA.h / 2, "center")
            labeled = True


def _render_lanes(surface, lane_emails, settings):
    n = max(1, len(lane_emails))
    lane_h = TL_AREA.h / n
    for i, email in enumerate(lane_emails):
        y = TL_AREA.y + i * lane_h
        main, _ = theme.account_color(settings.accounts[email].color)
        eventcard.draw_lane_label(surface, TL_X0 - 12, y + 18, main,
                                  settings.accounts[email].lane_label)
        if i:
            pygame.draw.line(surface, theme.C["panel_line"], (TL_X0, y), (TL_X1, y))


def _render_allday_pills(surface, allday, lane_emails, settings, hits) -> None:
    """河道（half/day 連續軸）模式的整日事件：各帳號泳道「頂部整日列」內的
    小膠囊——這條列由 layout_timeline_range 的 ALLDAY_STRIP_H 預留，計時卡
    從其下開始，膠囊與卡片物理上不共域（v1 膠囊浮在卡上，實機回報重疊）。
    最多 3 顆＋「+N」，可點開詳情。"""
    if not allday:
        return
    from deskbar.layout import ALLDAY_STRIP_H
    n = max(1, len(lane_emails))
    lane_h = TL_AREA.h / n
    for i, email in enumerate(lane_emails):
        evs = [e for e in allday if e.account == email]
        if not evs:
            continue
        acc = settings.accounts.get(email)
        main, _dark = theme.account_color(acc.color if acc else 0)
        y = TL_AREA.y + i * lane_h + (ALLDAY_STRIP_H - 28) / 2
        # 起點讓開泳道標籤（自訂標籤可能很長，如完整帳號前綴）
        label_text = acc.lane_label if acc else email
        label_w = theme.font(20).size(label_text)[0]
        x = TL_X0 + max(150, label_w + 40)
        shown = 0
        for e in evs[:3]:
            label = f"整日 {e.title}"   # 全形中點會豆腐（字型老坑）
            wpx = min(theme.font(18).size(label)[0] + 36, 260)
            r = pygame.Rect(int(x), int(y), int(wpx), 28)
            if r.right > TL_X1 - 56:
                break
            if not eventcard.draw_pill(surface, r, main, label):
                continue
            hits.append(Hit(Rect(r.x, r.y, r.w, r.h), "open_detail", e))
            x = r.right + 8
            shown += 1
        extra = len(evs) - shown
        if extra > 0 and x < TL_X1 - 50:
            _text(surface, f"+{extra}", 18, theme.C["muted"], x, y + 3)


def _render_now_line_range(surface, win_start, win_end, now: datetime) -> None:
    if not (win_start <= now <= win_end):
        return
    x = time_to_x_range(now, win_start, win_end, TL_X0, TL_X1)
    pygame.draw.line(surface, theme.C["now"], (x, 52), (x, 420), 2)
    pygame.draw.circle(surface, theme.C["now"], (round(x), 54), 5)   # iOS 式線頭圓點
    img = theme.text_surface(now.strftime("%H:%M"), 20, theme.C["now_text"])
    r = img.get_rect(midtop=(x, 54))
    pygame.draw.rect(surface, theme.C["now"], r.inflate(12, 6), border_radius=4)
    surface.blit(img, r)
