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


def render(surface, notes: list, ui: dict, area: Rect, now: datetime,
           mono: float) -> list:
    """notes＝NotesStore.list()；ui＝app.notes_ui；mono＝time.monotonic()
    （撕掉確認的逾時判斷用，跟 render 時刻解耦方便測試）。"""
    hits: list = []
    if ui["pending_id"] and mono - ui["pending_at"] > PENDING_TIMEOUT_S:
        ui["pending_id"] = None
    if not notes:
        cx = area.x + area.w / 2
        img = theme.font(28, bold=True).render("便條牆是空的", True, theme.C["text"])
        surface.blit(img, img.get_rect(center=(cx, area.y + 120)))
        for i, line in enumerate((
                "Mac：note 指令兩秒上牆（設定見網頁）",
                "手機：設定網頁 → 便條 → 輸入送出")):
            img = theme.font(22).render(line, True, theme.C["muted"])
            surface.blit(img, img.get_rect(center=(cx, area.y + 170 + i * 34)))
        return hits

    cols, rows = 3, 2
    gap = 14
    cw = (area.w - gap * (cols - 1)) / cols
    ch = (area.h - gap) / rows
    shown = notes[:cols * rows]
    for idx, n in enumerate(shown):
        col, row = idx % cols, idx // cols
        x = area.x + col * (cw + gap)
        y = area.y + row * (ch + gap)
        color = _STICKY[_h(n.id) % len(_STICKY)]
        pending = ui["pending_id"] == n.id
        # 便利貼本體畫在 SRCALPHA 上再微旋轉（±2°，由 id 決定、穩定不抖）
        pad = 14
        card = pygame.Surface((int(cw) - 8, int(ch) - 8), pygame.SRCALPHA)
        body = card.get_rect()
        base = _tint(color, 64 if theme.current_theme() == "dark" else 88)
        pygame.draw.rect(card, base, body, border_radius=10)
        pygame.draw.rect(card, _tint(color, 140), body, width=1, border_radius=10)
        tape = pygame.Rect(body.w // 2 - 34, 0, 68, 10)
        pygame.draw.rect(card, _tint(color, 110), tape,
                         border_bottom_left_radius=6, border_bottom_right_radius=6)
        lines = theme.wrap_lines(n.text, theme.font(22, bold=True),
                                 body.w - pad * 2, 4)
        ty = 22
        for line in lines:
            img = theme.font(22, bold=True).render(line, True, theme.C["text"])
            card.blit(img, (pad, ty))
            ty += 30
        ts = _fmt_ts(n.ts, now)
        if ts:
            img = theme.font(16).render(ts, True, theme.C["muted"])
            card.blit(img, (pad, body.h - 26))
        if pending:
            veil = pygame.Surface((body.w, body.h), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 120))
            card.blit(veil, (0, 0))
            img = theme.font(22, bold=True).render("再點一下撕掉", True,
                                                   theme.C["warn"])
            card.blit(img, img.get_rect(center=(body.w // 2, body.h // 2)))
        angle = ((_h(n.id) >> 4) % 5 - 2) * 1.0          # -2..+2 度
        rot = pygame.transform.rotozoom(card, angle, 1.0)
        surface.blit(rot, rot.get_rect(center=(x + cw / 2, y + ch / 2)))
        hits.append(Hit(Rect(x, y, cw, ch), "note_tap", n.id))
    extra = len(notes) - len(shown)
    if extra > 0:
        img = theme.font(18).render(f"＋{extra} 張", True, theme.C["muted"])
        surface.blit(img, img.get_rect(bottomright=(area.x + area.w,
                                                    area.y + area.h + 26)))
    return hits
