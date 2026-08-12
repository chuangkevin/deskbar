"""工作 Session UI 元件 (Pygame Dashboard Widget 與 Full Sessions View)。

1. Center Workbench 視圖 (render_center_view)：
   - 最多 6 張任務膠囊，寬畫面左右各 3 張，中間刻意留給喜喜活動。
   - 每張標示來源（Codex / Claude）、名稱、明確狀態、專案／時間與開啟動作。
   - 未讀完成標示「結果待看」；未讀進行中標示「有新進度」。

2. Dashboard Summary 視圖 (render_summary)：
   - 僅當活躍 (strictly < 30m) Session 數量 > 0 時繪製。
   - 數量 == 0 時：完全不繪製任何內容並回傳 0 高度與空 Hit 清單 (整塊消失)。

3. Full Sessions 視圖 (render_full_view)：
   - 呈現全部 strictly < 30m 之 Session。
   - 每列觸發 opaque open_id 排入 Action 佇列，按鈕標籤為 "開啟 App" / "開啟 Codex" / "開啟 Claude"。
"""
from __future__ import annotations

from datetime import datetime
import re
import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit, theme


def _text(surface: pygame.Surface, s: str, size: int, color, x: float, y: float,
          anchor: str = "topleft", bold: bool = False) -> pygame.Rect:
    img = theme.text_surface(s, size, color, bold=bold)
    r = img.get_rect(**{anchor: (round(x), round(y))})
    surface.blit(img, r)
    return r


def _status_pill_info(state: str) -> tuple[str, str]:
    """Return compact state copy that never depends on color alone."""
    if state == "result":
        return "就緒", "✓"
    elif state == "working":
        return "執行中", "▶"
    elif state == "waiting":
        return "等待回覆", "⏳"
    return "最近活動", "•"


def _source_chip_colors(source: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return the fixed source identity colors: Codex sky blue, Claude orange."""
    if source.lower().strip() in ("codex", "chatgpt"):
        return theme.C["work_codex"], theme.C["work_codex_text"]
    return theme.C["work_claude"], theme.C["work_claude_text"]


def render_center_view(surface: pygame.Surface, snap, settings, rect: Rect, now: datetime) -> list[Hit]:
    """Render two quiet task decks, leaving a central lane for Sisi."""
    hits: list[Hit] = []
    if snap is None or not hasattr(snap, "work_sessions") or snap.work_sessions is None:
        active_items = ()
    else:
        active_items = snap.work_sessions.active_items(now)

    dispatch_w, dispatch_h = 232, 46
    dispatch_x = rect.x + (rect.w - dispatch_w) / 2
    dispatch_y = rect.y + rect.h - dispatch_h - 10
    dispatch_rect = Rect(dispatch_x, dispatch_y, dispatch_w, dispatch_h)
    dispatch = pygame.Rect(round(dispatch_x), round(dispatch_y), dispatch_w, dispatch_h)
    pygame.draw.rect(surface, theme.C["work_claude"], dispatch, border_radius=23)
    pygame.draw.rect(surface, theme.C["panel_line"], dispatch, width=2, border_radius=23)
    _text(surface, "Claude Dispatch ↗", 18, theme.C["work_claude_text"],
          dispatch.centerx, dispatch.centery, anchor="center", bold=True)
    hits.append(Hit(dispatch_rect, "enqueue_claude_dispatch", None))

    dispatch_item = None
    for item in active_items:
        if getattr(item, "project_label", "") == "Claude Dispatch" and getattr(item, "progress_label", ""):
            dispatch_item = item
            break

    if dispatch_item is not None:
        progress_str = getattr(dispatch_item, "progress_label", "")
        _text(surface, f"Dispatch · {progress_str}", 14, theme.C["text"],
              dispatch.centerx, dispatch_y - 24, anchor="center", bold=True)
        ratio = 0.0
        match = re.match(r"^\s*(\d+)\s*/\s*(\d+)", progress_str)
        if match:
            try:
                done = int(match.group(1))
                total = int(match.group(2))
                if total > 0:
                    ratio = max(0.0, min(1.0, done / total))
            except (ValueError, ZeroDivisionError):
                ratio = 0.0

        bar_w, bar_h = dispatch_w, 6
        bar_x = dispatch_x
        bar_y = dispatch_y - 10
        bg_bar = pygame.Rect(round(bar_x), round(bar_y), bar_w, bar_h)
        pygame.draw.rect(surface, theme.C["panel_line"], bg_bar, border_radius=3)
        fill_w = round(bar_w * ratio)
        if fill_w > 0:
            fill_bar = pygame.Rect(round(bar_x), round(bar_y), fill_w, bar_h)
            pygame.draw.rect(surface, theme.C["work_claude"], fill_bar, border_radius=3)
    else:
        _text(surface, "Dispatch：等待 Claude 建立 task", 14, theme.C["muted"],
              dispatch.centerx, dispatch_y - 16, anchor="center")

    if not active_items:
        _text(surface, "目前無 30 分鐘內的活動 Session", 20, theme.C["muted"],
              rect.x + rect.w / 2, (rect.y + dispatch_y - 30) / 2, anchor="center")
        return hits

    items = active_items[:6]
    cols = 2 if rect.w >= 500 else 1
    rows = 3 if cols == 2 else min(6, max(1, len(items)))
    gap_y = 8
    # On wide displays Dispatch lives in Sisi's middle lane, so it does not
    # compete with either card deck. A single-column layout reserves space.
    content_h = rect.h if cols == 2 else max(0, dispatch_y - 36 - rect.y)
    card_h = min(112, (content_h - (rows - 1) * gap_y) / rows)
    deck_h = rows * card_h + (rows - 1) * gap_y
    deck_y = rect.y + max(0, (content_h - deck_h) / 2)
    if cols == 2:
        middle_lane = min(280, max(120, rect.w * 0.24))
        card_w = (rect.w - middle_lane) / 2
        col_x = (rect.x, rect.x + card_w + middle_lane)
    else:
        card_w = rect.w
        col_x = (rect.x,)

    for idx, item in enumerate(items):
        col = idx % cols
        row = idx // cols
        cx = col_x[col]
        cy = deck_y + row * (card_h + gap_y)
        card_rect = Rect(cx, cy, card_w, card_h)
        card = pygame.Rect(round(cx), round(cy), round(card_w), round(card_h))
        pygame.draw.rect(surface, theme.C["card"], card, border_radius=24)

        is_unread = snap.work_sessions.is_item_unread(item, now)
        state = getattr(item, "activity_state", "unknown")
        is_result = state == "result"
        border = theme.C["ok"] if (is_unread and is_result) else theme.C["panel_line"]
        pygame.draw.rect(surface, border, card, width=2 if (is_unread and is_result) else 1, border_radius=24)

        source_name = _source_display_name(item.source)
        source_color, _ = _source_chip_colors(item.source)
        pygame.draw.circle(surface, source_color, (round(cx + 23), round(cy + 22)), 6)
        _text(surface, source_name, 14, source_color, cx + 36, cy + 13, bold=True)

        btn_w, btn_h = 104, 28
        btn = pygame.Rect(round(cx + card_w - 14 - btn_w), round(cy + 10), btn_w, btn_h)
        pygame.draw.rect(surface, theme.C["bg"], btn, border_radius=14)
        pygame.draw.rect(surface, theme.C["panel_line"], btn, width=1, border_radius=14)
        _text(surface, f"開啟 {source_name}", 13, theme.C["text"], btn.centerx, btn.centery, anchor="center")

        title = item.label
        max_title_w = max(40, card_w - 36)
        while len(title) > 2 and theme.text_surface(title, 22, theme.C["text"], bold=True).get_width() > max_title_w:
            title = title[:-1]
        if title != item.label:
            title += "…"
        _text(surface, title, 22, theme.C["text"], cx + 18, cy + 41, bold=True)

        status, icon = _status_pill_info(state)
        status_color = theme.C["ok"] if is_result else (source_color if state == "working" else theme.C["muted"])
        if is_unread and is_result:
            badge = "結果待看"
        elif is_unread:
            badge = f"{status} · 有新進度"
        else:
            badge = status
        progress = getattr(item, "progress_label", "")
        if progress:
            badge = progress
        _text(surface, f"{icon} {badge}", 16, status_color, cx + 18, cy + 78, bold=True)

        relative = fmt_relative_time(item.last_active_at, now)
        detail = " · ".join(part for part in (getattr(item, "project_label", ""), relative) if part)
        if detail:
            while len(detail) > 2 and theme.text_surface(detail, 14, theme.C["muted"]).get_width() > 150:
                detail = detail[:-1]
            if detail.endswith("…"):
                detail = detail[:-1]
            elif len(detail) < len(" · ".join(part for part in (getattr(item, "project_label", ""), relative) if part)):
                detail += "…"
            _text(surface, detail, 14, theme.C["muted"], cx + card_w - 16, cy + 80, anchor="topright")

        hits.append(Hit(card_rect, "enqueue_work_session_action", item.open_id))

    return hits


def fmt_relative_time(dt: datetime | None, now: datetime) -> str:
    """計算相對時間字串，如 '剛才', '2分前'。"""
    if dt is None:
        return ""
    if dt.tzinfo is None and now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)
    elif dt.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=dt.tzinfo)

    diff_sec = max(0, (now - dt).total_seconds())
    if diff_sec < 60:
        return "剛才"
    mins = int(diff_sec // 60)
    return f"{mins}分前"


def _source_display_name(source: str) -> str:
    if not source:
        return "App"
    s = source.lower().strip()
    if s in ("codex", "chatgpt"):
        return "Codex"
    if s in ("claude",):
        return "Claude"
    return source.capitalize()


def render_summary(surface: pygame.Surface, snap, now: datetime,
                   x0: float = 1540, y0: float = 380, w: float = 360,
                   max_rows: int = 6) -> tuple[list[Hit], float]:
    """渲染右欄 Dashboard 摘要。無資料時整塊消失 (回傳 [], 0.0)。"""
    if snap is None or not hasattr(snap, "work_sessions") or snap.work_sessions is None:
        return [], 0.0

    active_items = snap.work_sessions.active_items(now)
    if not active_items:
        return [], 0.0

    hits: list[Hit] = []
    total_count = len(active_items)
    display_items = active_items[:max(1, max_rows)]

    title_s = f"工作 SESSIONS ({total_count})"
    _text(surface, title_s, 14, theme.C["muted"], x0, y0)

    row_y = y0 + 22
    row_h = 24
    for item in display_items:
        source_name = _source_display_name(item.source)
        rel_time = fmt_relative_time(item.last_active_at, now)

        tag_text = f"[{source_name}] {item.label}"
        max_label_w = w - 60
        img = theme.text_surface(tag_text, 14, theme.C["text2"])
        if img.get_width() > max_label_w:
            t = tag_text
            while len(t) > 3 and theme.text_surface(t + "…", 14, theme.C["text2"]).get_width() > max_label_w:
                t = t[:-1]
            tag_text = t + "…"

        _text(surface, tag_text, 14, theme.C["text2"], x0, row_y)
        _text(surface, rel_time, 13, theme.C["muted"], x0 + w, row_y, anchor="topright")
        row_y += row_h

    total_h = (row_y - y0) + 4
    summary_rect = Rect(x0, y0, w, total_h)
    hits.append(Hit(summary_rect, "open_work_sessions", None))

    return hits, total_h


def render_full_view(surface: pygame.Surface, snap, now: datetime, page: int = 0) -> list[Hit]:
    """渲染 Full Work Sessions 頁面，相容各種螢幕解析度 (1280x720, 1920x1080 與窄畫面)。"""
    hits: list[Hit] = []
    sw, sh = surface.get_size()

    surface.fill(theme.C["bg"])

    pygame.draw.rect(surface, theme.C["card"], pygame.Rect(0, 0, sw, 52))
    pygame.draw.line(surface, theme.C["panel_line"], (0, 52), (sw, 52), 1)

    back_btn_rect = Rect(16, 8, 100, 36)
    r = pygame.Rect(int(back_btn_rect.x), int(back_btn_rect.y), int(back_btn_rect.w), int(back_btn_rect.h))
    pygame.draw.rect(surface, theme.C["bg"], r, border_radius=6)
    pygame.draw.rect(surface, theme.C["panel_line"], r, width=1, border_radius=6)
    b_img = theme.text_surface("◀ 儀表板", 18, theme.C["text"])
    surface.blit(b_img, b_img.get_rect(center=r.center))
    hits.append(Hit(back_btn_rect, "go_dashboard", None))

    active_items = snap.work_sessions.active_items(now) if (snap and hasattr(snap, "work_sessions") and snap.work_sessions) else ()
    title_str = f"工作 Sessions ({len(active_items)})"
    _text(surface, title_str, 22, theme.C["text"], 130, 14, bold=True)

    if not active_items:
        empty_img = theme.text_surface("目前無 30 分鐘內的活躍 Sessions", 20, theme.C["muted"])
        surface.blit(empty_img, empty_img.get_rect(center=(sw // 2, sh // 2)))
        return hits

    start_y = 68
    max_height = sh - 110
    row_height = 54
    items_per_page = max(1, max_height // row_height)
    total_pages = max(1, (len(active_items) + items_per_page - 1) // items_per_page)
    current_page = max(0, min(page, total_pages - 1))

    page_items = active_items[current_page * items_per_page : (current_page + 1) * items_per_page]

    content_w = max(1, min(max(1, sw - 32), 1100))
    content_x = (sw - content_w) // 2

    y = float(start_y)
    for idx, item in enumerate(page_items):
        global_idx = current_page * items_per_page + idx + 1
        row_r = pygame.Rect(int(content_x), int(y), int(content_w), 46)

        pygame.draw.rect(surface, theme.C["card"], row_r, border_radius=8)
        pygame.draw.rect(surface, theme.C["panel_line"], row_r, width=1, border_radius=8)

        ord_text = f"#{global_idx}"
        _text(surface, ord_text, 16, theme.C["muted"], content_x + 12, y + 13)

        source_name = _source_display_name(item.source)
        src_color = theme.C["now"] if source_name == "Codex" else theme.C["ok"]
        _text(surface, source_name, 15, src_color, content_x + 52, y + 14, bold=True)

        act_state = getattr(item, "activity_state", "unknown")
        pill_text, pill_icon = _status_pill_info(act_state)
        pill_color = theme.C["ok"] if act_state == "result" else (theme.C["now"] if act_state == "working" else theme.C["muted"])

        btn_w = 100
        rel_time_w = 70
        label_x = content_x + 135
        status_x = label_x + 160
        label_max_w = max(60, status_x - label_x - 10)

        lbl = item.label
        lbl_img = theme.text_surface(lbl, 17, theme.C["text"])
        if lbl_img.get_width() > label_max_w:
            while len(lbl) > 2 and theme.text_surface(lbl + "…", 17, theme.C["text"]).get_width() > label_max_w:
                lbl = lbl[:-1]
            lbl = lbl + "…"
            lbl_img = theme.text_surface(lbl, 17, theme.C["text"])
        surface.blit(lbl_img, (label_x, y + 13))

        _text(surface, f"{pill_icon} {pill_text}", 14, pill_color, status_x, y + 14, bold=True)

        rel_time = fmt_relative_time(item.last_active_at, now)
        rel_time_x = content_x + content_w - btn_w - 20
        _text(surface, rel_time, 14, theme.C["muted"], rel_time_x, y + 15, anchor="topright")

        btn_h = 32
        btn_rect = Rect(content_x + content_w - btn_w - 8, y + 7, btn_w, btn_h)
        br = pygame.Rect(int(btn_rect.x), int(btn_rect.y), int(btn_rect.w), int(btn_rect.h))
        pygame.draw.rect(surface, theme.C["bg"], br, border_radius=6)
        pygame.draw.rect(surface, theme.C["panel_line"], br, width=1, border_radius=6)

        button_label = f"開啟 {source_name}"
        _text(surface, button_label, 14, theme.C["text"], br.centerx, br.centery, anchor="center")

        hits.append(Hit(btn_rect, "enqueue_work_session_action", item.open_id))

        y += row_height

    if total_pages > 1:
        page_str = f"{current_page + 1} / {total_pages}"
        _text(surface, page_str, 16, theme.C["text2"], sw // 2, sh - 32, anchor="center")

        if current_page > 0:
            prev_r = Rect(sw // 2 - 85, sh - 44, 60, 30)
            _draw_small_btn(surface, "< 上頁", prev_r)
            hits.append(Hit(prev_r, "work_sessions_page", current_page - 1))
        if current_page < total_pages - 1:
            next_r = Rect(sw // 2 + 25, sh - 44, 60, 30)
            _draw_small_btn(surface, "下頁 >", next_r)
            hits.append(Hit(next_r, "work_sessions_page", current_page + 1))

    return hits


def _draw_small_btn(surface: pygame.Surface, text: str, rect: Rect) -> None:
    r = pygame.Rect(int(rect.x), int(rect.y), int(rect.w), int(rect.h))
    pygame.draw.rect(surface, theme.C["card"], r, border_radius=4)
    pygame.draw.rect(surface, theme.C["panel_line"], r, width=1, border_radius=4)
    img = theme.text_surface(text, 14, theme.C["text"])
    surface.blit(img, img.get_rect(center=r.center))
