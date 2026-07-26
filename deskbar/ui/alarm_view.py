"""裝置端鬧鐘管理頁：左半既有鬧鐘清單、右半新增鬧鐘面板。"""

from __future__ import annotations

import pygame

from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme

WEEKDAY_CHARS = "一二三四五六日"   # 0=週一…6=週日，與 dashboard 的星期顯示一致
LABELS = ["提醒", "打卡", "吃藥", "會議"]

DIVIDER_X = 960


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def _btn(surface, label, x, y, w, h, action, data, hits, size=24, fg=None, active=False):
    r = pygame.Rect(x, y, w, h)
    bg = theme.C["now"] if active else theme.C["card"]
    pygame.draw.rect(surface, bg, r, border_radius=8)
    pygame.draw.rect(surface, theme.C["panel_line"], r, 1, border_radius=8)
    color = fg or (theme.C["now_text"] if active else theme.C["text"])
    img = theme.font(size).render(label, True, color)
    surface.blit(img, img.get_rect(center=r.center))
    hits.append(Hit(Rect(x, y, w, h), action, data))


def bump_draft(draft: dict, field: str, delta) -> dict:
    """更新新增鬧鐘暫存草稿（純函數，不碰 App/pygame 狀態，方便單元測試）。

    field="hour"/"minute"：delta 為位移量（分鐘固定以 5 為步進，由呼叫端決定）。
    field="day"：delta 為要切換的星期（0..6），存在則移除、不存在則加入。
    field="label"：忽略 delta，在 LABELS 之間循環一格。
    """
    if field == "hour":
        draft["hour"] = (draft["hour"] + delta) % 24
    elif field == "minute":
        draft["minute"] = (draft["minute"] + delta) % 60
    elif field == "day":
        days = set(draft.get("days") or ())
        if delta in days:
            days.discard(delta)
        else:
            days.add(delta)
        draft["days"] = days
    elif field == "label":
        draft["label_idx"] = (draft["label_idx"] + 1) % len(LABELS)
    return draft


def render(surface, store, draft, now) -> list[Hit]:
    hits: list[Hit] = []
    _text(surface, "鬧鐘", 32, theme.C["text"], 40, 24)
    _btn(surface, "完成", 1700, 20, 180, 52, "settings_done", None, hits)
    pygame.draw.line(surface, theme.C["panel_line"], (DIVIDER_X, 0), (DIVIDER_X, 480))

    _render_list(surface, store, hits)
    _render_draft(surface, draft, hits)
    return hits


def _render_list(surface, store, hits) -> None:
    alarms = store.list()[:4] if store is not None else []
    if not alarms:
        _text(surface, "尚無鬧鐘——右側可新增，或掃描設定頁 QR 用手機設定",
              22, theme.C["muted"], 40, 220)
        return
    y = 100
    for a in alarms:
        _text(surface, a.time, 40, theme.C["text"], 40, y)
        label = a.label if len(a.label) <= 12 else a.label[:12] + "…"
        _text(surface, label, 22, theme.C["text2"], 190, y + 4)
        # 防呆：只渲染合法的星期索引（0..6），避免壞資料撐爆索引。
        valid_days = sorted(d for d in a.days if isinstance(d, int) and 0 <= d <= 6)
        days = ("每" + "".join(WEEKDAY_CHARS[d] for d in valid_days)
                if valid_days else "一次性")
        _text(surface, days, 20, theme.C["muted"], 190, y + 34)
        toggle_label = "停用" if a.enabled else "啟用"
        _btn(surface, toggle_label, 560, y, 130, 52, "toggle_alarm", a.id, hits, size=22)
        _btn(surface, "刪除", 710, y, 100, 52, "delete_alarm", a.id, hits,
             size=22, fg=theme.C["warn"])
        y += 85


def _render_draft(surface, draft, hits) -> None:
    x0 = DIVIDER_X + 40
    _text(surface, "新增鬧鐘", 24, theme.C["muted"], x0, 32)
    h, m = draft["hour"], draft["minute"]
    _text(surface, f"{h:02d}:{m:02d}", 72, theme.C["text"], x0 + 265, 140, "midtop")

    _btn(surface, "時 －", x0, 230, 110, 56, "draft_hour", -1, hits)
    _btn(surface, "時 ＋", x0 + 120, 230, 110, 56, "draft_hour", 1, hits)
    _btn(surface, "分 －", x0 + 300, 230, 110, 56, "draft_minute", -5, hits)
    _btn(surface, "分 ＋", x0 + 420, 230, 110, 56, "draft_minute", 5, hits)

    days = draft.get("days") or set()
    dw = 118
    for d in range(7):
        bx = x0 + d * (dw + 8)
        _btn(surface, WEEKDAY_CHARS[d], bx, 300, dw, 52, "draft_day", d, hits,
             active=(d in days))

    label = LABELS[draft["label_idx"] % len(LABELS)]
    _btn(surface, f"標籤：{label}", x0, 364, 220, 56, "draft_label", None, hits, size=22)
    _btn(surface, "新增鬧鐘", x0 + 300, 364, 240, 60, "add_alarm", None, hits,
         size=26, active=True)
