"""工作 Session UI 元件 (Pygame Dashboard Widget 與 Full Sessions View)。

1. Dashboard Summary 視圖 (render_summary)：
   - 僅當活躍 (strictly < 30m) Session 數量 > 0 時繪製。
   - 數量 == 0 時：完全不繪製任何內容並回傳 0 高度與空 Hit 清單 (整塊消失)。
   - 最多保留最新 6 筆；摘要依面板高度顯示部分列與總數，點擊可看完整 6 筆。

2. Full Sessions 視圖 (render_full_view)：
   - 呈現全部 strictly < 30m 之 Session。
   - 每列按鈕觸發 opaque open_id 排入 Action 佇列。
   - 按鈕 UI 標籤僅為 "帶至前景" 或 "開啟 App"，絕不宣稱精確跳至對話。
   - 支援 1280x720、1920x1080 與窄畫面無文字重疊或出界。
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

        # 標籤 + 來源
        tag_text = f"[{source_name}] {item.label}"
        # 先算寬度避免撞到右側時間
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

    # 背景填色
    surface.fill(theme.C["bg"])

    # 頂欄帶
    pygame.draw.rect(surface, theme.C["card"], pygame.Rect(0, 0, sw, 52))
    pygame.draw.line(surface, theme.C["panel_line"], (0, 52), (sw, 52), 1)

    # ◀ 返回鈕
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

    # 列表版面計算
    start_y = 68
    max_height = sh - 110
    row_height = 54
    items_per_page = max(1, max_height // row_height)
    total_pages = max(1, (len(active_items) + items_per_page - 1) // items_per_page)
    current_page = max(0, min(page, total_pages - 1))

    page_items = active_items[current_page * items_per_page : (current_page + 1) * items_per_page]

    # 適應窄畫面與寬畫面
    content_w = max(1, min(max(1, sw - 32), 1100))
    content_x = (sw - content_w) // 2

    y = float(start_y)
    for idx, item in enumerate(page_items):
        global_idx = current_page * items_per_page + idx + 1
        row_r = pygame.Rect(int(content_x), int(y), int(content_w), 46)

        # 列邊框
        pygame.draw.rect(surface, theme.C["card"], row_r, border_radius=8)
        pygame.draw.rect(surface, theme.C["panel_line"], row_r, width=1, border_radius=8)

        # 序號 #1
        ord_text = f"#{global_idx}"
        _text(surface, ord_text, 16, theme.C["muted"], content_x + 12, y + 13)

        # 來源標籤 Badge
        source_name = _source_display_name(item.source)
        src_color = theme.C["now"] if source_name == "ChatGPT" else theme.C["ok"]
        _text(surface, source_name, 15, src_color, content_x + 52, y + 14, bold=True)

        # Safe CWD Label (適應窄屏)
        btn_w = 100
        rel_time_w = 70
        label_x = content_x + 145
        label_max_w = max(60, content_w - (label_x - content_x) - rel_time_w - btn_w - 30)

        lbl = item.label
        lbl_img = theme.text_surface(lbl, 17, theme.C["text"])
        if lbl_img.get_width() > label_max_w:
            while len(lbl) > 2 and theme.text_surface(lbl + "…", 17, theme.C["text"]).get_width() > label_max_w:
                lbl = lbl[:-1]
            lbl = lbl + "…"
            lbl_img = theme.text_surface(lbl, 17, theme.C["text"])
        surface.blit(lbl_img, (label_x, y + 13))

        # 相對時間
        rel_time = fmt_relative_time(item.last_active_at, now)
        rel_time_x = content_x + content_w - btn_w - 20
        _text(surface, rel_time, 14, theme.C["muted"], rel_time_x, y + 15, anchor="topright")

        # 「帶至前景」Action 按鈕
        btn_h = 32
        btn_rect = Rect(content_x + content_w - btn_w - 8, y + 7, btn_w, btn_h)
        br = pygame.Rect(int(btn_rect.x), int(btn_rect.y), int(btn_rect.w), int(btn_rect.h))
        pygame.draw.rect(surface, theme.C["bg"], br, border_radius=6)
        pygame.draw.rect(surface, theme.C["panel_line"], br, width=1, border_radius=6)

        button_label = f"開啟 {source_name}"
        _text(surface, button_label, 14, theme.C["text"], br.centerx, br.centery, anchor="center")

        # 點擊按鈕觸發 enqueue action
        hits.append(Hit(btn_rect, "enqueue_work_session_action", item.open_id))

        y += row_height

    # 頁碼切換
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
