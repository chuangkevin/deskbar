"""月視圖：每日 × 每帳號的「件數格」，點格跳該日日視圖。"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme
from deskbar.viewwin import WINDOW_FUTURE_DAYS, WINDOW_PAST_DAYS

LANE_LABEL_W = 72
HEADER_H = 28
DIM_FILL = (20, 20, 20)         # 資料窗口外的「假空」欄位底色


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def render_month(surface, events, lane_order: list[str], settings, win_start: datetime,
                 area: Rect, now: datetime) -> list[Hit]:
    hits: list[Hit] = []
    year, month = win_start.year, win_start.month
    days_in_month = calendar.monthrange(year, month)[1]
    today = now.date()
    # 已同步資料的窗口：[today-7, today+30]（含端點）。窗口外的欄位是「還沒同步」，
    # 不是「真的沒事」——之前直接顯示 0/空白會被誤讀成「這幾天真的沒事」（假空）。
    data_lo = today - timedelta(days=WINDOW_PAST_DAYS)
    data_hi = today + timedelta(days=WINDOW_FUTURE_DAYS)

    grid_x = area.x + LANE_LABEL_W
    grid_w = area.w - LANE_LABEL_W
    col_w = grid_w / days_in_month if days_in_month else grid_w
    n_lanes = max(1, len(lane_order))
    row_h = (area.h - HEADER_H) / n_lanes

    in_window: dict[int, bool] = {}
    for d in range(1, days_in_month + 1):
        day_date = date(year, month, d)
        x = grid_x + (d - 1) * col_w
        within = data_lo <= day_date <= data_hi
        in_window[d] = within
        if not within:
            pygame.draw.rect(surface, DIM_FILL,
                             pygame.Rect(int(x), int(area.y), max(1, round(col_w)),
                                         int(area.h)))
            _text(surface, "·", 16, theme.C["muted"], x + col_w / 2, area.y + 4, "midtop")
            continue
        is_today = day_date == today
        if is_today:
            pygame.draw.rect(surface, theme.C["now"],
                             pygame.Rect(int(x), int(area.y), max(1, round(col_w)),
                                         int(area.h)))
        color = theme.C["now_text"] if is_today else theme.C["muted"]
        _text(surface, str(d), 16, color, x + col_w / 2, area.y + 4, "midtop")

    for li, email in enumerate(lane_order):
        acc = settings.accounts[email]
        main, _ = theme.account_color(acc.color)
        y = area.y + HEADER_H + li * row_h
        _text(surface, acc.lane_label, 18, main, area.x, y + row_h / 2, "midleft")
        if li:
            pygame.draw.line(surface, theme.C["panel_line"], (area.x, y), (area.x + area.w, y))
        for d in range(1, days_in_month + 1):
            if not in_window[d]:
                continue      # 窗口外：不畫件數（不知道是不是真的沒事）、不給 goto_day hit
            day_date = date(year, month, d)
            count = sum(1 for e in events
                       if e.account == email and e.start.date() <= day_date <= e.end.date())
            x = grid_x + (d - 1) * col_w
            if count:
                _text(surface, str(count), 18, main, x + col_w / 2, y + row_h / 2, "center")
            hits.append(Hit(Rect(x, y, col_w, row_h), "goto_day", day_date))
    return hits
