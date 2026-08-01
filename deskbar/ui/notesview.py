"""中欄「便條」視圖：便利貼牆（3 欄 × 2 列，最多 6 張＋溢出計數）。

便條紙感的三個手段：
- 便利貼色盤（黃/粉/藍/綠/紫的 tint，深淺主題各自校過）輪流上色（依 id
  雜湊固定，不會每次重繪換色）
- 每張 ±2° 微傾斜（rotozoom 在全量重繪才發生，Pi 無逐幀成本）＋頂部一條
  更淡的「膠帶」
- 點一下→「再點一下撕掉」（5 秒逾時回復）——antinote 的即棄哲學，
  撕掉直接刪，沒有資源回收桶

輸入不在這裡（見 deskbar.notes 檔頭）；空狀態直接教兩條輸入路徑。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

TZ = ZoneInfo("Asia/Taipei")
# 便利貼色盤（原始 RGB；畫時經 theme.col 校 BGR、依主題 lerp）
_STICKY = [(255, 214, 90), (255, 160, 180), (120, 190, 255),
           (150, 226, 160), (200, 170, 255)]
PENDING_TIMEOUT_S = 5.0


def new_state() -> dict:
    return {"pending_id": None, "pending_at": 0.0}


def _h(s: str) -> int:
    v = 0
    for ch in s:
        v = (v * 131 + ord(ch)) & 0xFFFFFFFF
    return v


def _tint(color, alpha: int):
    a = max(0, min(255, alpha)) / 255.0
    bg = theme.C["bg"]
    c = theme.col(color)
    return tuple(round(bg[i] + (c[i] - bg[i]) * a) for i in range(3))


def _fmt_ts(iso: str, now: datetime) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    mins = int((now - dt).total_seconds() // 60)
    if mins < 1:
        return "剛剛"
    if mins < 60:
        return f"{mins} 分鐘前"
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    return f"{dt.month}/{dt.day}"


PAGE_SIZE = 6


def page_count(n_items: int) -> int:
    return max(1, (n_items + PAGE_SIZE - 1) // PAGE_SIZE)


def render(surface, notes: list, ui: dict, area: Rect, now: datetime,
           mono: float, page: int = 0) -> list:
    """notes＝NotesStore.list()；ui＝app.notes_ui；mono＝time.monotonic()
    （撕掉確認的逾時判斷用，跟 render 時刻解耦方便測試）。"""
    hits: list = []
    if ui["pending_id"] and mono - ui["pending_at"] > PENDING_TIMEOUT_S:
        ui["pending_id"] = None
    if not notes:
        cx = area.x + area.w / 2
        img = theme.text_surface("便條牆是空的", 28, theme.C["text"], bold=True)
        surface.blit(img, img.get_rect(center=(cx, area.y + 120)))
        for i, line in enumerate((
                "Mac：note 指令兩秒上牆（設定見網頁）",
                "手機：設定網頁 → 便條 → 輸入送出")):
            img = theme.text_surface(line, 22, theme.C["muted"])
            surface.blit(img, img.get_rect(center=(cx, area.y + 170 + i * 34)))
        return hits

    cols, rows = 3, 2
    gap = 14
    cw = (area.w - gap * (cols - 1)) / cols
    ch = (area.h - gap) / rows
    pages = page_count(len(notes))
    page = max(0, min(page, pages - 1))
    shown = notes[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    S = 2   # 超取樣倍率：2 倍畫、旋轉時縮回 1 倍——rotozoom 的縮小濾波就是
            # 免費的邊緣抗鋸齒（1 倍直轉的圓角與斜邊在低解析面板上鋸齒明顯，
            # 實機驗收：「邊緣粗糙有夠不精緻」）
    for idx, n in enumerate(shown):
        col, row = idx % cols, idx // cols
        x = area.x + col * (cw + gap)
        y = area.y + row * (ch + gap)
        ci = getattr(n, "color", -1)
        color = _STICKY[ci] if 0 <= ci < len(_STICKY) \
            else _STICKY[_h(n.id) % len(_STICKY)]   # 沒指定就依 id 輪色
        pending = ui["pending_id"] == n.id
        pad = 14 * S
        card = pygame.Surface(((int(cw) - 8) * S, (int(ch) - 8) * S),
                              pygame.SRCALPHA)
        body = card.get_rect()
        base = _tint(color, 64 if theme.current_theme() == "dark" else 88)
        pygame.draw.rect(card, base, body, border_radius=10 * S)
        pygame.draw.rect(card, _tint(color, 140), body, width=S,
                         border_radius=10 * S)
        tape = pygame.Rect(body.w // 2 - 34 * S, 0, 68 * S, 10 * S)
        pygame.draw.rect(card, _tint(color, 110), tape,
                         border_bottom_left_radius=6 * S,
                         border_bottom_right_radius=6 * S)
        # 優先序徽章（右上角，避開左上內文起點與中央膠帶）：順序＝優先序，
        # 網頁拖動排序後這裡的編號即時跟上
        seq = page * PAGE_SIZE + idx + 1
        pygame.draw.circle(card, _tint(color, 190),
                           (body.w - 22 * S, 22 * S), 14 * S)
        num = theme.text_surface(str(seq), 16 * S, theme.C["text"], bold=True)
        card.blit(num, num.get_rect(center=(body.w - 22 * S, 22 * S)))
        lines = theme.wrap_lines(n.text, theme.font(22 * S, bold=True),
                                 body.w - pad * 2, 4)
        ty = 22 * S
        for line in lines:
            img = theme.text_surface(line, 22 * S, theme.C["text"], bold=True)
            card.blit(img, (pad, ty))
            ty += 30 * S
        ts = _fmt_ts(n.ts, now)
        if ts:
            img = theme.text_surface(ts, 16 * S, theme.C["muted"])
            card.blit(img, (pad, body.h - 26 * S))
        if pending:
            veil = pygame.Surface((body.w, body.h), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 120))
            card.blit(veil, (0, 0))
            img = theme.text_surface("再點一下撕掉", 22 * S, theme.C["warn"],
                                     bold=True)
            card.blit(img, img.get_rect(center=(body.w // 2, body.h // 2)))
        angle = ((_h(n.id) >> 4) % 5 - 2) * 1.0          # -2..+2 度
        cx, cy = x + cw / 2, y + ch / 2
        # 柔和落影（同形黑面同角度旋轉、右下偏移）：紙貼在牆上的縱深感
        shadow = pygame.Surface(body.size, pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 66), shadow.get_rect(),
                         border_radius=10 * S)
        sh = pygame.transform.rotozoom(shadow, angle, 1.0 / S)
        surface.blit(sh, sh.get_rect(center=(cx + 3, cy + 4)))
        rot = pygame.transform.rotozoom(card, angle, 1.0 / S)
        surface.blit(rot, rot.get_rect(center=(cx, cy)))
        hits.append(Hit(Rect(x, y, cw, ch), "note_tap", n.id))
    if pages > 1:
        cx = area.x + area.w / 2 - (pages - 1) * 11
        for i in range(pages):
            color = theme.C["text2"] if i == page else theme.C["panel_line"]
            pygame.draw.circle(surface, color, (round(cx + i * 22),
                                                round(area.y + area.h + 16)), 5)
        img = theme.text_surface(f"{page + 1}/{pages}", 16, theme.C["muted"])
        surface.blit(img, img.get_rect(topright=(area.x + area.w,
                                                 area.y + area.h + 8)))
    return hits
