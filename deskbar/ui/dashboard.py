from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time as _time, timedelta

import pygame

from deskbar.layout import Rect, layout_timeline_range, split_allday, time_to_x_range
from deskbar.ui import Hit
from deskbar.ui import agenda, icons, monthgrid, theme, usagewidget, weekgrid
from deskbar.viewwin import agenda_window, data_window, view_window, window_label
from deskbar.weather import code_text

# 三欄版面（2026-07 三欄重構）：左＝時鐘/日期/天氣/同步狀態，中＝行事曆時間軸，
# 右＝Claude usage 油表。座標全部集中在這裡，其餘子渲染（agenda/weekgrid/monthgrid/
# grid_range/now_line/lanes）一律吃 TL_AREA 或 module 常量，不再各自硬寫魔術數字。
PANEL_W, TL_X0, TL_X1 = 400, 420, 1520
TL_AREA = Rect(TL_X0, 52, TL_X1 - TL_X0, 368)
CHIP_MAX_X = 1250                        # 整日 chips／溢出小字的絕對右界（早於寬度鈕留白，
                                          # 即使沒有窗口標籤／回到今天鈕分走版面也不會逼近按鈕）
USAGE_X0, USAGE_W = 1540, 360            # 右欄 1540..1900：跟左/中欄一樣在螢幕右緣留 20px
SPAN_LABELS = {"half": "半天", "day": "日", "week": "週", "month": "月"}
# 寬度鈕／模式鈕改放中欄頂帶右側（原本在畫面最右側，現在中欄變窄，兩顆鈕改貼中欄右界，
# 右欄完全不放任何頂帶元素）。
SPAN_BTN = Rect(1290, 2, 110, 48)
MODE_BTN = Rect(1408, 2, 110, 48)
GOTO_NOW_W, GOTO_NOW_H = 110, 40        # 「回到今天」鈕：緊貼寬度鈕左側
TOPBAR_GAP = 16                          # 頂帶固定區塊之間的最小留白
CHIP_ROW_Y, CHIP_ROW_H = 8, 28           # 整日 chips／溢出小字所在的列
IMMINENT_WINDOW = timedelta(minutes=5)  # 「迫近」定義：尚未開始、且開始時間在 now 起 5 分鐘內
PULSE_PERIOD_S = 2.0                    # 呼吸邊框的完整週期（秒）


def imminent_events(events, now: datetime) -> list:
    """純函數：從 events 中挑出「即將開始」的行程——尚未開始（start > now），
    且開始時間落在 now 起算 5 分鐘內（含 5 分鐘整）。已經開始（start <= now）的一律不算。

    給 App 主迴圈用便宜的純時間比較判斷要不要維持每圈重繪（見 app.py），
    也給 render() 內部決定哪些色塊要疊呼吸邊框。
    """
    return [e for e in events if now < e.start <= now + IMMINENT_WINDOW]


def _pulse_t(now: datetime) -> float:
    """呼吸亮度 0~1：sin(now.timestamp() * 2π / 週期) 映射到 [0,1]。"""
    phase = math.sin(now.timestamp() * (2 * math.pi / PULSE_PERIOD_S))
    return (phase + 1) / 2


def _pulse_color(main, now: datetime):
    """帳號主色與白色之間依呼吸亮度插值，供迫近行程色塊的外框使用。"""
    t = _pulse_t(now)
    return tuple(round(c + (255 - c) * t) for c in main)


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _chip_btn(surface, label, rect: Rect, action, hits, size=22):
    r = pygame.Rect(int(rect.x), int(rect.y), int(rect.w), int(rect.h))
    pygame.draw.rect(surface, theme.C["card"], r, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=8)
    img = theme.font(size).render(label, True, theme.C["text"])
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
    goto_now_rect = (Rect(SPAN_BTN.x - GOTO_NOW_W, 4, GOTO_NOW_W, GOTO_NOW_H)
                     if show_goto_now else None)
    leftmost = goto_now_rect.x if goto_now_rect is not None else SPAN_BTN.x

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
          weather_tick=0) -> list[Hit]:
    hits: list[Hit] = []
    tz = now.tzinfo
    span = settings.view_span
    anchor_or_now = anchor if anchor is not None else now
    win_start, win_end = view_window(span, anchor_or_now, tz,
                                     start_hour=settings.start_hour, end_hour=settings.end_hour)

    _render_panel(surface, snap, settings, now, hits, clock_anim, weather_tick)
    pygame.draw.line(surface, theme.C["panel_line"], (PANEL_W, 0), (PANEL_W, 480))
    pygame.draw.line(surface, theme.C["panel_line"], (TL_X1, 0), (TL_X1, 480))

    lane_emails = [e for e in settings.accounts if settings.accounts[e].calendars] \
        or list(snap.statuses)
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

    _render_allday(surface, allday, settings, hits, topbar.chip_right_x)
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
        placed, overflow = layout_timeline_range(timed, lane_emails, win_start, win_end, TL_AREA)
        _render_lanes(surface, lane_emails, settings)
        imminent_ids = {e.id for e in imminent_events(timed, now)}
        for p in placed:
            main, dark = theme.account_color(settings.accounts[p.event.account].color)
            r = pygame.Rect(int(p.rect.x), int(p.rect.y) + 2, int(p.rect.w), int(p.rect.h) - 4)
            pygame.draw.rect(surface, dark, r, border_radius=6)
            if p.event.id in imminent_ids:
                pygame.draw.rect(surface, _pulse_color(main, now), r, width=3, border_radius=6)
            label = ("◀ " if p.clip_l else "") + p.event.title + (" ▶" if p.clip_r else "")
            fitted = theme.truncate_to_width(label, theme.font(22), r.width - 12)
            if fitted:                             # 量不出能放下的內容就乾脆不畫
                _text(surface, fitted, 22, main, r.x + 8, r.y + r.height / 2 - 14)
            hits.append(Hit(p.rect, "open_detail", p.event))
        if overflow:
            _text(surface, f"＋{len(overflow)} 更多", 20, theme.C["muted"], TL_X1, 44, "topright")
        _render_now_line_range(surface, win_start, win_end, now)

    # 右欄：Claude usage 油表——獨立呼叫，不吃 TL_AREA、不產生 hits（純資訊面板，
    # 跟左欄時鐘/天氣一樣不可互動），畫在最後純粹是慣例（跟中欄內容互不重疊，順序無關）。
    usagewidget.render(surface, snap.usage, now, USAGE_X0, USAGE_W)
    return hits


def _render_panel(surface, snap, settings, now, hits, clock_anim=None, weather_tick=0):
    """左欄（0..PANEL_W=400）：時鐘/日期/天氣/同步狀態。三欄重構把這欄從 480 縮到
    400px，時鐘改用 digit_h=96（4 卡+冒號實測總寬 342px，遠低於 360 的安全上限），
    其餘文字/圖示座標跟著往內收，確保沒有任何元素畫出 PANEL_W 之外。"""
    w = snap.weather
    if w is not None:
        from deskbar.ui import weatherfx
        weatherfx.draw(surface, w.code, weather_tick, w=PANEL_W)   # 背景層：畫在時鐘/文字之前
    anim = clock_anim if clock_anim else (now.strftime("%H:%M"), 1.0)
    from deskbar.ui import flipclock
    flipclock.draw(surface, 24, 34, now.strftime("%H:%M"), anim[0], anim[1],
                   digit_h=96)    # 4 卡+冒號實測總寬 342px，PANEL_W=400 內綽綽有餘
    wd = "週" + "一二三四五六日"[now.weekday()]
    _text(surface, f"{now.month}月{now.day}日 {wd}", 24, theme.C["text2"], 24, 150)
    if w is not None:
        age = (now - w.fetched_at).total_seconds()
        stale = "（舊）" if age > 7200 else ""
        _text(surface, f"{code_text(w.code)} {round(w.temp)}° {w.label}{stale}",
              24, theme.C["text"], 24, 196)
        _text(surface, f"{round(w.tmin)}° / {round(w.tmax)}°", 20, theme.C["muted"], 24, 230)
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
        dot = theme.col((93, 202, 165)) if ok else theme.C["warn"]
    pygame.draw.circle(surface, dot, (32, 449), 5)
    _text(surface, msg, 18, theme.C["muted"], 46, 440)
    hits.append(Hit(Rect(20, 26, 370, 130), "open_alarms", None))
    hits.append(Hit(Rect(20, 424, 290, 48), "force_sync", None))    # 左下同步狀態＝點擊強制同步
    gear = Rect(320, 396, 72, 72)
    icons.draw_gear(surface, 352, 432, 18, theme.C["muted"])
    hits.append(Hit(gear, "open_settings", None))


def _allday_label(e) -> str:
    return f"整日 · {e.title}"


def _layout_allday_chips(allday: list, right_limit: float) -> int:
    """回傳「放得下」的 chips 數 k（0..len(allday)）：chips[0:k] 個別都落在
    [TL_X0, right_limit] 內；若 k<len(allday)，還要保證「＋N 整日」溢出小字
    本身也放得下——放不下就再往回收一顆 chip 讓位，直到放得下或 k=0 為止。
    只量寬度（Font.size，不必真的 render 出 Surface），供 render 與測試共用。
    """
    n = len(allday)
    if n == 0:
        return 0
    widths = [theme.font(20).size(_allday_label(e))[0] + 20 for e in allday]
    xs = []
    x = TL_X0
    for w in widths:
        xs.append(x)
        x += w + 10

    k = 0
    for i in range(n):
        if xs[i] + widths[i] <= right_limit:
            k = i + 1
        else:
            break

    while 0 < k < n:
        remaining = n - k
        overflow_w = theme.font(20).size(f"＋{remaining} 整日")[0] + 20
        if xs[k] + overflow_w <= right_limit:
            break
        k -= 1
    return k


def _render_allday(surface, allday: list, settings, hits, right_limit: float):
    """整日 chips 從 TL_X0 起橫向排列；放不下的一律收成右側一顆「＋N 整日」
    小字（點開 open_allday_list 浮層列出全部整日事件標題），確保無論資料量
    多寡都不會畫出 right_limit 之外，跟頂帶其他固定元素相撞。"""
    if not allday:
        return
    n = len(allday)
    k = _layout_allday_chips(allday, right_limit)

    x = TL_X0
    for e in allday[:k]:
        main, dark = theme.account_color(settings.accounts[e.account].color)
        label = _allday_label(e)
        w = theme.font(20).size(label)[0] + 20
        img = theme.font(20).render(label, True, main)
        pygame.draw.rect(surface, dark, pygame.Rect(x, CHIP_ROW_Y, w, CHIP_ROW_H),
                         border_radius=5)
        surface.blit(img, (x + 10, CHIP_ROW_Y + 3))
        hits.append(Hit(Rect(x, CHIP_ROW_Y, w, CHIP_ROW_H), "open_detail", e))
        x += w + 10

    if k < n:
        remaining = n - k
        label = f"＋{remaining} 整日"
        w = theme.font(20).size(label)[0] + 20
        img = theme.font(20).render(label, True, theme.C["muted"])
        pygame.draw.rect(surface, theme.C["card"], pygame.Rect(x, CHIP_ROW_Y, w, CHIP_ROW_H),
                         border_radius=5)
        surface.blit(img, (x + 10, CHIP_ROW_Y + 3))
        hits.append(Hit(Rect(x, CHIP_ROW_Y, w, CHIP_ROW_H), "open_allday_list", allday))


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
        band.fill((20, 20, 20, 170))
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
        pygame.draw.rect(surface, main, pygame.Rect(TL_X0 - 14, int(y) + 4, 6, int(lane_h) - 8))
        _text(surface, settings.accounts[email].lane_label, 22, main, TL_X0 + 6, int(y) + 4)
        if i:
            pygame.draw.line(surface, theme.C["panel_line"], (TL_X0, y), (TL_X1, y))


def _render_now_line_range(surface, win_start, win_end, now: datetime) -> None:
    if not (win_start <= now <= win_end):
        return
    x = time_to_x_range(now, win_start, win_end, TL_X0, TL_X1)
    pygame.draw.line(surface, theme.C["now"], (x, 52), (x, 420), 3)
    img = theme.font(20).render(now.strftime("%H:%M"), True, theme.C["now_text"])
    r = img.get_rect(midtop=(x, 54))
    pygame.draw.rect(surface, theme.C["now"], r.inflate(12, 6), border_radius=4)
    surface.blit(img, r)
