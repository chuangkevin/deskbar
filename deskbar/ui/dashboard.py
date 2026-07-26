from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pygame

from deskbar.layout import Rect, layout_timeline_range, split_allday, time_to_x_range
from deskbar.ui import Hit
from deskbar.ui import agenda, icons, monthgrid, theme
from deskbar.viewwin import data_window, view_window, window_label
from deskbar.weather import code_text

PANEL_W, TL_X0, TL_X1 = 480, 500, 1900
TL_AREA = Rect(TL_X0, 52, TL_X1 - TL_X0, 368)
SPAN_LABELS = {"half": "半天", "day": "日", "week": "週", "month": "月"}
SPAN_BTN = Rect(1650, 2, 115, 48)
MODE_BTN = Rect(1775, 2, 115, 48)
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
                   show_goto_now: bool, show_label: bool) -> TopbarLayout:
    """純函數：只算幾何，不畫、不動 surface。回到今天鈕寬 110，緊貼寬度鈕左側
    （右邊界＝SPAN_BTN.x，中間不留縫）；窗口標籤右對齊到「回到今天鈕或寬度鈕，
    取較左者」的左側再減 16px 留白；整日 chips 的可用右界＝以上所有「這一幀有出現」
    的元素中最靠左的 x，再減 16px。任何資料量／任何標籤長度下，四者之間必定
    保有 >=16px 間隔，不會互相重疊。"""
    goto_now_rect = (Rect(SPAN_BTN.x - GOTO_NOW_W, 4, GOTO_NOW_W, GOTO_NOW_H)
                     if show_goto_now else None)
    leftmost = goto_now_rect.x if goto_now_rect is not None else SPAN_BTN.x

    label_text = ""
    label_right_x = leftmost - TOPBAR_GAP
    if show_label:
        label_text = window_label(span, anchor_or_now, win_start, win_end)
        label_w = theme.font(22).size(label_text)[0]
        leftmost = label_right_x - label_w

    chip_right_x = leftmost - TOPBAR_GAP
    return TopbarLayout(goto_now_rect, label_text, label_right_x, chip_right_x)


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

    lane_emails = [e for e in settings.accounts if settings.accounts[e].calendars] \
        or list(snap.statuses)
    visible = [e for e in snap.events
               if e.account in lane_emails and e.end > win_start and e.start < win_end]
    allday, timed = split_allday(visible)

    show_goto_now = anchor is not None
    show_label = anchor is not None or span != "day"
    topbar = _layout_topbar(span, anchor_or_now, win_start, win_end, show_goto_now, show_label)

    _render_allday(surface, allday, settings, hits, topbar.chip_right_x)
    _render_span_mode_buttons(surface, settings, hits)
    if topbar.goto_now_rect is not None:
        _chip_btn(surface, "回到今天", topbar.goto_now_rect, "goto_now", hits, size=20)
    if topbar.label_text:
        _text(surface, topbar.label_text, 22, theme.C["text2"],
             topbar.label_right_x, 22, "midright")

    if settings.view_mode == "agenda":
        upcoming = [e for e in snap.events
                    if e.account in lane_emails and e.end > now]
        hits += agenda.render_agenda(surface, upcoming, settings, now,
                                     now + timedelta(days=31), now, TL_AREA)
    elif span == "month":
        hits += monthgrid.render_month(surface, visible, lane_emails, settings, win_start,
                                       TL_AREA, now)
    else:
        _render_grid_range(surface, span, win_start, win_end)
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
            if r.width > 40:                      # 塊夠寬就顯示標題；週檢視用小字
                clipped = surface.subsurface(r.clip(surface.get_rect()))
                if span == "week":
                    _text(clipped, label, 18, main, 6, r.height // 2 - 12)
                else:
                    _text(clipped, label, 22, main, 8, r.height // 2 - 14)
            hits.append(Hit(p.rect, "open_detail", p.event))
        if overflow:
            _text(surface, f"＋{len(overflow)} 更多", 20, theme.C["muted"], TL_X1, 44, "topright")
        _render_now_line_range(surface, win_start, win_end, now)
    return hits


def _render_panel(surface, snap, settings, now, hits, clock_anim=None, weather_tick=0):
    w = snap.weather
    if w is not None:
        from deskbar.ui import weatherfx
        weatherfx.draw(surface, w.code, weather_tick)   # 背景層：畫在時鐘/文字之前
    anim = clock_anim if clock_anim else (now.strftime("%H:%M"), 1.0)
    from deskbar.ui import flipclock
    flipclock.draw(surface, 36, 40, now.strftime("%H:%M"), anim[0], anim[1],
                   digit_h=118)   # 4 卡+冒號總寬 ≤440，收在左面板 480px 內
    wd = "週" + "一二三四五六日"[now.weekday()]
    _text(surface, f"{now.month}月{now.day}日 {wd}", 28, theme.C["text2"], 44, 190)
    if w is not None:
        age = (now - w.fetched_at).total_seconds()
        stale = "（舊）" if age > 7200 else ""
        _text(surface, f"{code_text(w.code)} {round(w.temp)}° {w.label}{stale}",
              28, theme.C["text"], 44, 250)
        _text(surface, f"{round(w.tmin)}° / {round(w.tmax)}°", 24, theme.C["muted"], 44, 290)
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
    pygame.draw.circle(surface, dot, (52, 442), 5)
    _text(surface, msg, 20, theme.C["muted"], 66, 430)
    hits.append(Hit(Rect(30, 30, 470, 150), "open_alarms", None))
    hits.append(Hit(Rect(40, 424, 300, 48), "force_sync", None))    # 左下同步狀態＝點擊強制同步
    gear = Rect(396, 396, 72, 72)
    icons.draw_gear(surface, 432, 432, 20, theme.C["muted"])
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


def _render_grid_range(surface, span, win_start, win_end):
    if span == "week":
        d = win_start
        while d < win_end:
            x = time_to_x_range(d, win_start, win_end, TL_X0, TL_X1)
            pygame.draw.line(surface, theme.C["grid"], (x, 52), (x, 420), 2)
            wd = "一二三四五六日"[d.weekday()]
            _text(surface, wd, 20, theme.C["muted"], x + 6, 434)
            d += timedelta(days=1)
    else:                                   # half / day：每 2 小時整點一條淡格線
        t = win_start.replace(minute=0, second=0, microsecond=0)
        if t < win_start:
            t += timedelta(hours=1)
        while t <= win_end:
            if t.hour % 2 == 0:
                x = time_to_x_range(t, win_start, win_end, TL_X0, TL_X1)
                pygame.draw.line(surface, theme.C["grid"], (x, 52), (x, 420))
                _text(surface, f"{t.hour:02d}", 20, theme.C["muted"], x, 434, "midtop")
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
