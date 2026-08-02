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
    S = 2   # 超取樣倍率：2 倍畫、smoothscale 縮回 1 倍——縮小濾波就是免費的
            # 邊緣抗鋸齒。第一版走「微旋轉＋rotozoom」，實機兩度驗收都是
            # 「邊緣粗糙不精緻」：SRCALPHA 邊緣在旋轉重採樣下必然起毛邊。
            # 正擺＋smoothscale 直邊零鋸齒、圓角平滑，也更符合乾淨專業的路線。
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
            # 「✕」字元在部分 CJK 字型是豆腐方塊，提示走純文字
            img = theme.text_surface("點右上紅鈕撕掉", 22 * S, theme.C["warn"],
                                     bold=True)
            card.blit(img, img.get_rect(center=(body.w // 2, body.h // 2)))
            # ✕ 鈕蓋在徽章位置：撕除的第二段必須點中這顆小目標（誤觸防呆——
            # 舊版整張卡都是確認目標，連點兩下就誤撕，實機驗收踩到）
            bx, by = body.w - 22 * S, 22 * S
            pygame.draw.circle(card, theme.C["warn"], (bx, by), 16 * S)
            fg = (255, 255, 255)
            pygame.draw.line(card, fg, (bx - 7 * S, by - 7 * S),
                             (bx + 7 * S, by + 7 * S), 3 * S)
            pygame.draw.line(card, fg, (bx + 7 * S, by - 7 * S),
                             (bx - 7 * S, by + 7 * S), 3 * S)
        # 正擺＋smoothscale 縮回 1 倍（見 S 的註解）；落影右下偏移給縱深
        dst = (int(cw) - 8, int(ch) - 8)
        px, py = round(x) + 4, round(y) + 4
        shadow = pygame.Surface(body.size, pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 66), shadow.get_rect(),
                         border_radius=10 * S)
        surface.blit(pygame.transform.smoothscale(shadow, dst), (px + 3, py + 4))
        surface.blit(pygame.transform.smoothscale(card, dst), (px, py))
        if pending:
            # 後 append 的在命中判定是上層（app 端 reversed 掃描）：
            # ✕ 區蓋過整卡的取消區
            hits.append(Hit(Rect(x, y, cw, ch), "note_cancel", n.id))
            hits.append(Hit(Rect(x + cw - 64, y, 64, 64), "note_del", n.id))
        else:
            hits.append(Hit(Rect(x, y, cw, ch), "note_arm", n.id))
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
