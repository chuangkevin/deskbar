"""中欄「待辦事項」視圖：Linear assignedIssues 卡片牆（2 欄 × 4 列）。

視覺沿用 eventcard 語彙（左色條＋淡底＋中性文字），但色相來自 Linear 的
工作流狀態色（state.color，Linear 桌面同款），一眼可讀「進行中/待做」。
排序已由 deskbar.linear 做好（緊急→高→中→低→無，同級比到期日）。

空狀態三階：沒設 Key → 指去手機網頁貼；設了還沒同步到 → 同步中；
同步過但空 → 目前沒有待辦。逾期以 warn 色標「逾期 N 天」。
"""
from __future__ import annotations

import pygame

from deskbar.linear import state_rgb
from deskbar.ui import eventcard, theme

_PRIO_LABEL = {1: "緊急", 2: "高"}     # 3/4/0 不掛標——滿版標籤＝沒有標籤


def _text(surface, s, size, color, x, y, anchor="topleft", bold=False):
    img = theme.font(size, bold=bold).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


PAGE_SIZE = 8


def page_count(n_items: int) -> int:
    return max(1, (n_items + PAGE_SIZE - 1) // PAGE_SIZE)


def _pager(surface, area, page, pages) -> None:
    """頁點指示（●○○），畫在牆底下緣中央；單頁不畫。"""
    if pages <= 1:
        return
    cx = area.x + area.w / 2 - (pages - 1) * 11
    for i in range(pages):
        color = theme.C["text2"] if i == page else theme.C["panel_line"]
        pygame.draw.circle(surface, color, (round(cx + i * 22),
                                            round(area.y + area.h + 16)), 5)


def render(surface, snap, settings, area, now, page: int = 0) -> list:
    """回傳 hits（目前無可點元素，回空清單維持介面一致）。
    page 由 app 持有（左右滑動翻頁），這裡夾在合法範圍內顯示。"""
    items = snap.linear
    if not getattr(settings, "linear_api_key", ""):
        _text(surface, "尚未連接 Linear", 28, theme.C["text"],
              area.x + area.w / 2, area.y + 140, "center", bold=True)
        _text(surface, "手機開設定網頁 → 裝置設定 → 貼上 Linear API Key",
              22, theme.C["muted"], area.x + area.w / 2, area.y + 186, "center")
        return []
    if not items:
        if snap.linear_at is None:
            _text(surface, "同步中…", 26, theme.C["muted"],
                  area.x + area.w / 2, area.y + 160, "center")
        else:
            _text(surface, "目前沒有待辦", 26, theme.C["muted"],
                  area.x + area.w / 2, area.y + 160, "center")
        return []

    cols, rows = 2, 4
    gap = 10
    cw = (area.w - gap) / cols
    ch = (area.h - gap * (rows - 1)) / rows
    pages = page_count(len(items))
    page = max(0, min(page, pages - 1))
    shown = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    for idx, it in enumerate(shown):
        col, row = idx % cols, idx // cols
        x = area.x + col * (cw + gap)
        y = area.y + row * (ch + gap)
        main = theme.col(state_rgb(it.state_color))
        card = pygame.Rect(int(x), int(y), int(cw), int(ch))
        pygame.draw.rect(surface, eventcard.fill_color(main), card,
                         border_radius=eventcard.RADIUS)
        pygame.draw.rect(surface, eventcard.border_color(main), card, width=1,
                         border_radius=eventcard.RADIUS)
        bar = pygame.Rect(card.x + 4, card.y + 4, 4, card.h - 8)
        pygame.draw.rect(surface, main, bar, border_radius=2)

        tx = card.x + 18
        # 第一行：identifier（muted）＋狀態名（狀態色）＋優先度/到期（靠右）
        r = _text(surface, it.identifier, 16, theme.C["muted"], tx, card.y + 10)
        _text(surface, it.state_name, 16, main, r.right + 12, card.y + 10)
        right_x = card.right - 12
        if it.due is not None:
            overdue = (it.due - now.date()).days
            if overdue < 0:
                due_label, due_color = f"逾期 {-overdue} 天", theme.C["warn"]
            elif overdue == 0:
                due_label, due_color = "今天到期", theme.C["warn"]
            else:
                due_label, due_color = f"{it.due.month}/{it.due.day}", theme.C["muted"]
            r2 = _text(surface, due_label, 16, due_color, right_x, card.y + 10,
                       "topright", bold=overdue <= 0)
            right_x = r2.left - 12
        prio = _PRIO_LABEL.get(it.priority)
        if prio:
            _text(surface, prio, 16, theme.C["warn" if it.priority == 1 else "now"],
                  right_x, card.y + 10, "topright", bold=True)
        # 第二行：標題（中性粗體）；第三行：專案名（有才畫）
        title = theme.truncate_to_width(it.title, theme.font(22, bold=True),
                                        card.w - 30)
        if title:
            _text(surface, title, 22, theme.C["text"], tx, card.y + 34, bold=True)
        if it.project and card.h >= 78:
            proj = theme.truncate_to_width(it.project, theme.font(16), card.w - 30)
            _text(surface, proj, 16, theme.C["muted"], tx, card.y + 62)
    _pager(surface, area, page, pages)
    if pages > 1:
        _text(surface, f"{page + 1}/{pages}", 16, theme.C["muted"],
              area.x + area.w, area.y + area.h + 8, "topright")
    return []
