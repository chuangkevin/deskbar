"""週檔河道：帳號×日格子（v4.1 新增，取代週檔的連續軸細色條路徑）。

規格（docs/superpowers/specs/2026-07-26-deskbar-design.md 第 11 節 v4.1）：
- 列＝帳號（沿用泳道左緣色條＋標籤），欄＝7 天（欄頭同 agenda：星期＋月/日，
  今天用 theme.C["now"] 色字）。
- 每格內至多 floor(格高/26) 條微列「HH:MM 標題」（18px），整日事件加「整」字
  徽章前綴；放不下的收成「＋N」。
- 今天那一欄畫細框；格子整格皆為觸控目標 → Hit(action="goto_day", data=該日
  date)（點格跳日視圖，跟月視圖一致），不對個別行程另開 open_detail hit——
  1440px/7 天太窄，塞不下可靠的逐行點擊熱區，看詳情改成「先跳日視圖再點」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme
from deskbar.ui.agenda import day_header_label

LANE_LABEL_W = 72
HEADER_H = 32
MICRO_ROW_H = 26
MICRO_FONT = 18
BADGE_FONT = 12


def _events_for_cell(events, email: str, day: date) -> list:
    """該帳號、該日的事件：計時事件依 start.date()==day；整日事件依
    [start.date(), end.date()) 涵蓋 day（Google 全天事件 end 為排他端點）。"""
    out = []
    for e in events:
        if e.account != email:
            continue
        if e.all_day:
            if e.start.date() <= day < e.end.date():
                out.append(e)
        elif e.start.date() == day:
            out.append(e)
    return out


def _draw_micro_row(surface, e, settings, x: float, y: float, w: float) -> None:
    acc = settings.accounts.get(e.account)
    main, _dark = theme.account_color(acc.color if acc else 0)
    text_x = x + 2
    if e.all_day:
        # 整日＝實心色點（原本的橘色「整」badge 太吵，Apple 語彙：點＝整日）
        pygame.draw.circle(surface, main, (round(text_x + 4), round(y + MICRO_ROW_H / 2)), 3)
        text_x += 12
        label = e.title
    else:
        label = f"{e.start.strftime('%H:%M')} {e.title}"
    max_w = x + w - text_x - 2
    fitted = theme.truncate_to_width(label, theme.font(MICRO_FONT), max_w)
    if fitted:
        # 中性文字（帳號識別已由「列」承擔）——滿格飽和彩字是舊語彙（eventcard 檔頭）
        img = theme.text_surface(fitted, MICRO_FONT, theme.C["text"])
        surface.blit(img, (text_x, y + MICRO_ROW_H / 2 - img.get_height() / 2))


def render_week(surface, events, lane_order: list[str], settings, week_start_date: date,
                now: datetime, tz, area: Rect) -> list[Hit]:
    hits: list[Hit] = []
    today = now.date()
    grid_x = area.x + LANE_LABEL_W
    grid_w = area.w - LANE_LABEL_W
    col_w = grid_w / 7
    n_lanes = max(1, len(lane_order))
    row_h = (area.h - HEADER_H) / n_lanes

    days = [week_start_date + timedelta(days=i) for i in range(7)]
    for i, d in enumerate(days):
        x = grid_x + i * col_w
        cx = x + col_w / 2
        is_today = d == today
        color = theme.C["now"] if is_today else theme.C["text2"]
        img = theme.text_surface(day_header_label(d), 20, color)
        surface.blit(img, img.get_rect(midtop=(cx, area.y + 4)))
        if i:
            pygame.draw.line(surface, theme.C["grid"], (x, area.y), (x, area.y + area.h))
        if is_today:
            # 整欄 1px 細框，跟 monthgrid「今天」的視覺語彙一致。
            pygame.draw.rect(surface, theme.C["now"],
                             pygame.Rect(int(x), int(area.y), max(1, round(col_w)),
                                         int(area.h)), width=1)

    for li, email in enumerate(lane_order):
        acc = settings.accounts[email]
        main, _dark = theme.account_color(acc.color)
        y = area.y + HEADER_H + li * row_h
        from deskbar.ui import eventcard
        eventcard.draw_lane_label(surface, area.x, y + row_h / 2, main,
                                  acc.lane_label, size=18)
        if li:
            pygame.draw.line(surface, theme.C["panel_line"], (area.x, y), (area.x + area.w, y))

        for i, d in enumerate(days):
            x = grid_x + i * col_w
            cell = Rect(x, y, col_w, row_h)
            evs = _events_for_cell(events, email, d)
            evs.sort(key=lambda e: (not e.all_day, e.start))    # 整日排最前
            capacity = max(1, int(row_h // MICRO_ROW_H))
            shown = min(len(evs), capacity)
            overflow = len(evs) - shown
            if overflow > 0:
                shown = max(0, capacity - 1)      # 留最後一格給「＋N」
                overflow = len(evs) - shown
            for ri in range(shown):
                _draw_micro_row(surface, evs[ri], settings, x, y + ri * MICRO_ROW_H, col_w)
            if overflow > 0:
                label = f"＋{overflow}"
                img2 = theme.text_surface(label, MICRO_FONT, theme.C["muted"])
                ry = y + shown * MICRO_ROW_H
                surface.blit(img2, (x + 4, ry + MICRO_ROW_H / 2 - img2.get_height() / 2))
            hits.append(Hit(cell, "goto_day", d))
    return hits
