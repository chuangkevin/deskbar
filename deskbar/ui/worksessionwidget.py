"""工作 Session UI 元件 (Pygame Dashboard Widget 與 Full Sessions View)。

1. Center Workbench 視圖 (render_center_view)：
   - 2 欄 × 3 列緊湊卡片 (窄 rect 時退為 1 欄)，最多顯示 6 筆。
   - 每格標示顯眼來源 chip (Codex / Claude)、專案 basename、明確安全狀態 pill
     (結果已就緒 / 執行中 / 等待更新 / 最近活動) 與相對時間。
   - 未讀且為 result 時強調「結果待看」；未讀而非 result 標「有新進度」。

2. Dashboard Summary 視圖 (render_summary)：
   - 僅當活躍 (strictly < 30m) Session 數量 > 0 時繪製。
   - 數量 == 0 時：完全不繪製任何內容並回傳 0 高度與空 Hit 清單 (整塊消失)。

3. Full Sessions 視圖 (render_full_view)：
   - 呈現全部 strictly < 30m 之 Session。
   - 每列觸發 opaque open_id 排入 Action 佇列，按鈕標籤為 "開啟 App" / "開啟 Codex" / "開啟 Claude"。
"""
from __future__ import annotations

from datetime import datetime
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
    """Return (display_text, icon_prefix) for status pill.
    Never relies on color alone because text explicitly states the status.
    """
    if state == "result":
        return "結果已就緒", "✓"
    elif state == "working":
        return "執行中", "▶"
    elif state == "waiting":
        return "等待更新", "⏳"
    else:
        return "最近活動", "•"


def _source_chip_colors(source: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return the fixed source identity colors: Codex sky blue, Claude orange."""
    if source.lower().strip() in ("codex", "chatgpt"):
        return theme.C["work_codex"], theme.C["work_codex_text"]
    return theme.C["work_claude"], theme.C["work_claude_text"]


def render_center_view(surface: pygame.Surface, snap, settings, rect: Rect, now: datetime) -> list[Hit]:
    """渲染中欄 Center View 工作台 (最多 6 張 2x3 緊湊卡片)。"""
    hits: list[Hit] = []
    if snap is None or not hasattr(snap, "work_sessions") or snap.work_sessions is None:
        active_items = ()
    else:
        active_items = snap.work_sessions.active_items(now)

    if not active_items:
        empty_str = "目前無 30 分鐘內的活動 Session"
        _text(surface, empty_str, 20, theme.C["muted"],
              rect.x + rect.w / 2, rect.y + rect.h / 2, anchor="center")
        return hits

    items = active_items[:6]
    cols = 2 if rect.w >= 500 else 1
    rows = 3 if cols == 2 else min(6, max(1, len(items)))
    gap_x = 16 if cols == 2 else 0
    gap_y = 10
    card_w = (rect.w - (cols - 1) * gap_x) / cols
    card_h = (rect.h - (rows - 1) * gap_y) / rows

    for idx, item in enumerate(items):
        c = idx % cols
        r = idx // cols
        cx = rect.x + c * (card_w + gap_x)
        cy = rect.y + r * (card_h + gap_y)
        card_rect = Rect(cx, cy, card_w, card_h)

        pr = pygame.Rect(round(cx), round(cy), round(card_w), round(card_h))
        pygame.draw.rect(surface, theme.C["card"], pr, border_radius=10)

        is_unread = snap.work_sessions.is_item_unread(item, now) if hasattr(snap, "work_sessions") and snap.work_sessions else False
        act_state = getattr(item, "activity_state", "unknown")
        is_result = (act_state == "result")

        # Border
        border_color = theme.C["ok"] if (is_unread and is_result) else theme.C["panel_line"]
        border_w = 2 if (is_unread and is_result) else 1
        pygame.draw.rect(surface, border_color, pr, width=border_w, border_radius=10)

        # Source Chip (Codex vs Claude)
        source_name = _source_display_name(item.source)
        chip_bg, chip_text = _source_chip_colors(item.source)
        chip_w, chip_h = 56, 22
        chip_r = pygame.Rect(round(cx + 12), round(cy + 10), chip_w, chip_h)
        pygame.draw.rect(surface, chip_bg, chip_r, border_radius=5)
        _text(surface, source_name, 13, chip_text, chip_r.centerx, chip_r.centery, anchor="center", bold=True)

        # Unread badge
        badge_w = 0
        if is_unread:
            badge_text = "結果待看" if is_result else "有新進度"
            badge_bg = theme.C["ok"] if is_result else theme.C["now"]
            badge_w, badge_h = 76, 22
            badge_r = pygame.Rect(round(cx + card_w - 12 - badge_w), round(cy + 10), badge_w, badge_h)
            pygame.draw.rect(surface, badge_bg, badge_r, border_radius=6)
            _text(surface, badge_text, 13, theme.C["now_text"], badge_r.centerx, badge_r.centery, anchor="center", bold=True)

        # Level 1: Title (Prominent session title)
        title_x = cx + 76
        max_title_w = max(40, card_w - (title_x - cx) - (badge_w + 16 if is_unread else 16))
        lbl = item.label
        lbl_img = theme.text_surface(lbl, 18, theme.C["text"], bold=True)
        if lbl_img.get_width() > max_title_w:
            while len(lbl) > 2 and theme.text_surface(lbl + "…", 18, theme.C["text"], bold=True).get_width() > max_title_w:
                lbl = lbl[:-1]
            lbl += "…"
        _text(surface, lbl, 18, theme.C["text"], title_x, cy + 11, bold=True)

        # Level 2: Project Basename
        proj_str = f"專案：{item.project_label}" if getattr(item, "project_label", "") else ""
        if proj_str:
            max_proj_w = max(40, card_w - 24)
            p_lbl = proj_str
            p_img = theme.text_surface(p_lbl, 14, theme.C["text2"])
            if p_img.get_width() > max_proj_w:
                while len(p_lbl) > 2 and theme.text_surface(p_lbl + "…", 14, theme.C["text2"]).get_width() > max_proj_w:
                    p_lbl = p_lbl[:-1]
                p_lbl += "…"
            _text(surface, p_lbl, 14, theme.C["text2"], cx + 12, cy + 40)

        # Level 3: Status Pill & Relative Time
        pill_text, pill_icon = _status_pill_info(act_state)
        rel_time = fmt_relative_time(item.last_active_at, now)

        if act_state == "result":
            pill_color = theme.C["ok"]
        elif act_state == "working":
            pill_color = chip_bg
        else:
            pill_color = theme.C["muted"]

        full_status_str = f"{pill_icon} {pill_text}" + (f" · {rel_time}" if rel_time else "")
        _text(surface, full_status_str, 14, pill_color, cx + 12, cy + 68, bold=True)

        # Action Button (bottom right)
        btn_w, btn_h = 92, 24
        btn_r = pygame.Rect(round(cx + card_w - 12 - btn_w), round(cy + card_h - 32), btn_w, btn_h)
        pygame.draw.rect(surface, theme.C["bg"], btn_r, border_radius=6)
        pygame.draw.rect(surface, theme.C["panel_line"], btn_r, width=1, border_radius=6)
        btn_label = f"開啟 {source_name}"
        btn_img = theme.text_surface(btn_label, 13, theme.C["text"])
        surface.blit(btn_img, btn_img.get_rect(center=btn_r.center))

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
