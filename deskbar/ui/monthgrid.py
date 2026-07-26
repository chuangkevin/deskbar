"""月視圖：每日表頭數字＋每帳號的「件數膠囊」，點格跳該日日視圖。

設計原則（2026-07-26 重設計，修掉「窗口外＝一大片黑洞」的觀感問題）：
每一天永遠都畫日期數字表頭；窗口外（還沒同步到的日子）只是表頭數字變灰、
不給點擊、不畫件數膠囊——不再整欄塗一塊實色底，避免看起來像「這幾天壞掉了」。
"""
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
PILL_H = 22


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _draw_today_header(surface, cx: float, top: float, day: int) -> None:
    """今天的表頭數字「反白」：小圓角色塊（theme.C["now"]）承底，深色字，
    跟 dashboard 現在時間線的時刻標籤同一套視覺語彙，一眼認出「今天」。"""
    img = theme.font(16).render(str(day), True, theme.C["now_text"])
    r = img.get_rect(midtop=(cx, top))
    pygame.draw.rect(surface, theme.C["now"], r.inflate(10, 6), border_radius=6)
    surface.blit(img, r)


def _draw_count_pill(surface, count: int, main, dark, cx: float, cy: float) -> None:
    """帳號色深底＋主色字的件數膠囊，置中畫在該帳號那一列、那一天的格子裡。"""
    label = str(count)
    img = theme.font(18).render(label, True, main)
    w = max(img.get_width() + 14, PILL_H)
    rect = pygame.Rect(0, 0, w, PILL_H)
    rect.center = (round(cx), round(cy))
    pygame.draw.rect(surface, dark, rect, border_radius=PILL_H // 2)
    surface.blit(img, img.get_rect(center=rect.center))


def render_month(surface, events, lane_order: list[str], settings, win_start: datetime,
                 area: Rect, now: datetime) -> list[Hit]:
    hits: list[Hit] = []
    year, month = win_start.year, win_start.month
    days_in_month = calendar.monthrange(year, month)[1]
    today = now.date()
    # 已同步資料的窗口：[today-7, today+30]（含端點）。窗口外的欄位是「還沒同步」，
    # 不是「真的沒事」——直接顯示 0/空白會被誤讀成「這幾天真的沒事」（假空）。
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
        cx = x + col_w / 2
        within = data_lo <= day_date <= data_hi
        in_window[d] = within
        is_today = day_date == today

        if within:
            # 格線只畫窗口內的天——窗口外維持「沒有格線的暗色日期行」，不刻意
            # 用實色塊圈起來，才不會又變成新的一種「黑洞」。
            pygame.draw.line(surface, theme.C["grid"], (x, area.y), (x, area.y + area.h))
        if is_today:
            # 整欄 1px 帳號無關的細框，取代舊版整根實心色柱——「今天」只是個
            # 淡淡的邊界提示，不該搶走整欄件數膠囊的注意力。
            pygame.draw.rect(surface, theme.C["now"],
                             pygame.Rect(int(x), int(area.y), max(1, round(col_w)),
                                         int(area.h)), width=1)
            _draw_today_header(surface, cx, area.y + 4, d)
        else:
            color = theme.C["text2"] if within else theme.C["muted"]
            _text(surface, str(d), 16, color, cx, area.y + 4, "midtop")

    for li, email in enumerate(lane_order):
        acc = settings.accounts[email]
        main, dark = theme.account_color(acc.color)
        y = area.y + HEADER_H + li * row_h
        _text(surface, acc.lane_label, 18, main, area.x, y + row_h / 2, "midleft")
        if li:
            pygame.draw.line(surface, theme.C["panel_line"], (area.x, y), (area.x + area.w, y))
        for d in range(1, days_in_month + 1):
            if not in_window[d]:
                continue      # 窗口外：不畫件數膠囊（不知道是不是真的沒事）、不給 goto_day hit
            day_date = date(year, month, d)
            count = sum(1 for e in events
                       if e.account == email and e.start.date() <= day_date <= e.end.date())
            x = grid_x + (d - 1) * col_w
            if count:
                _draw_count_pill(surface, count, main, dark, x + col_w / 2, y + row_h / 2)
            hits.append(Hit(Rect(x, y, col_w, row_h), "goto_day", day_date))
    return hits
