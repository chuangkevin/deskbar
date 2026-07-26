"""行程模式：一天一塊直欄（v4.1 全面重寫，取代舊版橫向卡片流）。

規格（docs/superpowers/specs/2026-07-26-deskbar-design.md 第 11 節 v4.1）：
- day/half：單欄，欄寬吃滿整個 area、行高放大到 48px 觸控達標。
- week/month：7 欄並排（錨點所在週對齊週一起算，見 viewwin.agenda_window）。
- 每欄：整日行程置頂（「整日」徽章＋標題），其後計時行程依開始時間排序；
  容量放不下時尾行收成「＋N」；空欄只留欄頭＋一條 muted 底線；整個窗口零
  行程時，改在區域正中央顯示「這段期間沒有行程」。
- 每一行給 open_detail hit（34px 行高屬既知的觸控例外）；容器欄本身不另設 hit
  （跟 weekgrid「整格是 goto_day 觸控目標」是不同的互動模型）。
"""
from __future__ import annotations

from datetime import date as _date, datetime, time as _time, timedelta
from zoneinfo import ZoneInfo

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

ROW_H = 34
ROW_H_WIDE = 48          # n_days==1（day/half 全寬單欄）：放大到觸控達標
HEADER_H = 32
WEEKDAY_CHARS = "一二三四五六日"


def day_header_label(d: _date) -> str:
    """欄頭文案：星期＋月/日，例如「一 7/27」。weekgrid 沿用同一支保持視覺一致。"""
    return f"{WEEKDAY_CHARS[d.weekday()]} {d.month}/{d.day}"


def _draw_column_header(surface, cx: float, top: float, d: _date, is_today: bool) -> None:
    color = theme.C["now"] if is_today else theme.C["text2"]
    img = theme.font(20).render(day_header_label(d), True, color)
    surface.blit(img, img.get_rect(midtop=(cx, top)))


def _draw_row(surface, e, settings, rect: Rect, font_size: int) -> None:
    """畫一列（整日或計時皆共用）：行首 3px 帳號色條＋內容。"""
    acc = settings.accounts.get(e.account)
    main, _dark = theme.account_color(acc.color if acc else 0)
    pygame.draw.rect(surface, main,
                     pygame.Rect(int(rect.x), int(rect.y) + 2, 3, max(1, int(rect.h) - 4)))
    text_x = rect.x + 10
    if e.all_day:
        badge_img = theme.font(12).render("整日", True, theme.C["now_text"])
        badge_rect = pygame.Rect(0, 0, badge_img.get_width() + 8, badge_img.get_height() + 4)
        badge_rect.midleft = (round(text_x), round(rect.y + rect.h / 2))
        pygame.draw.rect(surface, theme.C["now"], badge_rect, border_radius=4)
        surface.blit(badge_img, badge_img.get_rect(center=badge_rect.center))
        text_x = badge_rect.right + 8
        label = e.title
    else:
        label = f"{e.start.strftime('%H:%M')} {e.title}"
    max_w = rect.x + rect.w - text_x - 8
    fitted = theme.truncate_to_width(label, theme.font(font_size), max_w)
    if fitted:
        img = theme.font(font_size).render(fitted, True, theme.C["text"])
        surface.blit(img, (text_x, rect.y + rect.h / 2 - img.get_height() / 2))


def _assign_day(e, start_date: _date, days: list[_date], day_events: dict) -> None:
    if e.all_day:
        d0 = max(e.start.date(), start_date)
        d1 = min(e.end.date(), days[-1] + timedelta(days=1))     # 排他端點
        d = d0
        while d < d1:
            if d in day_events:
                day_events[d].append(e)
            d += timedelta(days=1)
    else:
        d = e.start.date()
        if d not in day_events:
            # 跨窗口邊界的計時行程（理論上不該出現，因為呼叫端已先過濾窗口，
            # 這裡是防禦性收邊）：夾到窗口第一天或最後一天，不憑空消失。
            d = start_date if d < start_date else days[-1]
        day_events[d].append(e)


def render_agenda(surface, events, settings, start_date: _date, n_days: int,
                  now: datetime, tz: ZoneInfo, area: Rect) -> list[Hit]:
    hits: list[Hit] = []
    n = max(1, n_days)
    win_start = datetime.combine(start_date, _time(0, 0), tzinfo=tz)
    win_end = win_start + timedelta(days=n)
    in_window = [e for e in events if e.end > win_start and e.start < win_end]

    if not in_window:
        img = theme.font(26).render("這段期間沒有行程", True, theme.C["muted"])
        surface.blit(img, img.get_rect(center=(area.x + area.w / 2, area.y + area.h / 2)))
        return hits

    days = [start_date + timedelta(days=i) for i in range(n)]
    day_events: dict[_date, list] = {d: [] for d in days}
    for e in in_window:
        _assign_day(e, start_date, days, day_events)

    col_w = area.w / n
    row_h = ROW_H_WIDE if n == 1 else ROW_H
    today = now.date()

    for i, d in enumerate(days):
        x = area.x + i * col_w
        cx = x + col_w / 2
        is_today = d == today
        _draw_column_header(surface, cx, area.y + 4, d, is_today)
        if i:
            pygame.draw.line(surface, theme.C["grid"], (x, area.y), (x, area.y + area.h))

        allday_evs = sorted((e for e in day_events[d] if e.all_day), key=lambda e: e.title)
        timed_evs = sorted((e for e in day_events[d] if not e.all_day), key=lambda e: e.start)
        ordered = allday_evs + timed_evs

        body_y = area.y + HEADER_H
        body_h = area.h - HEADER_H
        capacity = max(1, int(body_h // row_h))

        if not ordered:
            if not is_today:
                line_y = area.y + HEADER_H - 1
                pygame.draw.line(surface, theme.C["muted"], (x, line_y), (x + col_w, line_y))
            continue

        shown = min(len(ordered), capacity)
        overflow = len(ordered) - shown
        if overflow > 0:
            shown = max(0, capacity - 1)          # 留最後一格給「＋N」
            overflow = len(ordered) - shown

        for ri in range(shown):
            row_rect = Rect(x, body_y + ri * row_h, col_w, row_h)
            _draw_row(surface, ordered[ri], settings, row_rect, 20)
            hits.append(Hit(row_rect, "open_detail", ordered[ri]))

        if overflow > 0:
            label = f"＋{overflow}"
            img = theme.font(18).render(label, True, theme.C["muted"])
            ry = body_y + shown * row_h
            surface.blit(img, (x + 10, ry + row_h / 2 - img.get_height() / 2))

    return hits
