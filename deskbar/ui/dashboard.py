from datetime import datetime, time as _t, timedelta

import pygame

from deskbar.layout import Rect, layout_timeline, split_allday, time_to_x
from deskbar.ui import Hit
from deskbar.ui import icons
from deskbar.ui import theme
from deskbar.weather import code_text

PANEL_W, TL_X0, TL_X1 = 480, 500, 1900
TL_AREA = Rect(TL_X0, 52, TL_X1 - TL_X0, 368)


def _text(surface, s, size, color, x, y, anchor="topleft"):
    img = theme.font(size).render(s, True, color)
    r = img.get_rect(**{anchor: (x, y)})
    surface.blit(img, r)
    return r


def render(surface, snap, settings, now: datetime, clock_anim=None) -> list[Hit]:
    hits: list[Hit] = []
    day = now.date()
    _render_panel(surface, snap, settings, now, hits, clock_anim)
    pygame.draw.line(surface, theme.C["panel_line"], (PANEL_W, 0), (PANEL_W, 480))
    lane_emails = [e for e in settings.accounts if settings.accounts[e].calendars] \
        or list(snap.statuses)
    visible = [e for e in snap.events
               if e.account in lane_emails and e.start.date() <= day <= e.end.date()]
    allday, timed = split_allday(visible)
    _render_allday(surface, allday, settings, hits)
    _render_grid(surface, settings)
    placed, overflow = layout_timeline(
        timed, lane_emails, day, settings.start_hour, settings.end_hour, TL_AREA)
    _render_lanes(surface, lane_emails, settings)
    for p in placed:
        main, dark = theme.account_color(settings.accounts[p.event.account].color)
        r = pygame.Rect(int(p.rect.x), int(p.rect.y) + 2, int(p.rect.w), int(p.rect.h) - 4)
        pygame.draw.rect(surface, dark, r, border_radius=6)
        label = ("◀ " if p.clip_l else "") + p.event.title + (" ▶" if p.clip_r else "")
        if r.width > 40:
            clipped = surface.subsurface(r.clip(surface.get_rect()))
            _text(clipped, label, 22, main, 8, r.height // 2 - 14)
        hits.append(Hit(p.rect, "open_detail", p.event))
    if overflow:
        _text(surface, f"＋{len(overflow)} 更多", 20, theme.C["muted"], TL_X1, 44, "topright")
    _render_now_line(surface, settings, now)
    return hits


def _render_panel(surface, snap, settings, now, hits, clock_anim=None):
    anim = clock_anim if clock_anim else (now.strftime("%H:%M"), 1.0)
    from deskbar.ui import flipclock
    flipclock.draw(surface, 40, 40, now.strftime("%H:%M"), anim[0], anim[1])
    wd = "週" + "一二三四五六日"[now.weekday()]
    _text(surface, f"{now.month}月{now.day}日 {wd}", 28, theme.C["text2"], 44, 190)
    w = snap.weather
    if w is not None:
        age = (now - w.fetched_at).total_seconds()
        stale = "（舊）" if age > 7200 else ""
        _text(surface, f"{code_text(w.code)} {round(w.temp)}° {w.label}{stale}",
              28, theme.C["text"], 44, 250)
        _text(surface, f"{round(w.tmin)}° / {round(w.tmax)}°", 24, theme.C["muted"], 44, 290)
    ok = all(s.ok for s in snap.statuses.values()) if snap.statuses else True
    ages = [s.last_sync for s in snap.statuses.values() if s.last_sync]
    if ages:
        mins = int((now - max(ages)).total_seconds() // 60)
        msg = f"已同步 {mins} 分鐘前" if ok else "部分帳號同步異常"
    else:
        msg = "等待首次同步"
    dot = (93, 202, 165) if ok else theme.C["warn"]
    pygame.draw.circle(surface, dot, (52, 442), 5)
    _text(surface, msg, 20, theme.C["muted"], 66, 430)
    hits.append(Hit(Rect(30, 30, 470, 150), "open_alarms", None))
    gear = Rect(396, 396, 72, 72)
    icons.draw_gear(surface, 432, 432, 20, theme.C["muted"])
    hits.append(Hit(gear, "open_settings", None))


def _render_allday(surface, allday, settings, hits):
    x = TL_X0
    for e in allday[:4]:
        main, dark = theme.account_color(settings.accounts[e.account].color)
        label = f"整日 · {e.title}"
        img = theme.font(20).render(label, True, main)
        w = img.get_width() + 20
        pygame.draw.rect(surface, dark, pygame.Rect(x, 8, w, 28), border_radius=5)
        surface.blit(img, (x + 10, 11))
        hits.append(Hit(Rect(x, 8, w, 28), "open_detail", e))
        x += w + 10


def _render_grid(surface, settings):
    for h in range(settings.start_hour, settings.end_hour + 1, 2):
        x = TL_X0 + (h - settings.start_hour) / (settings.end_hour - settings.start_hour) \
            * (TL_X1 - TL_X0)
        pygame.draw.line(surface, theme.C["grid"], (x, 52), (x, 420))
        _text(surface, f"{h:02d}", 20, theme.C["muted"], x, 434, "midtop")


def _render_lanes(surface, lane_emails, settings):
    n = max(1, len(lane_emails))
    lane_h = TL_AREA.h / n
    for i, email in enumerate(lane_emails):
        y = TL_AREA.y + i * lane_h
        main, _ = theme.account_color(settings.accounts[email].color)
        pygame.draw.rect(surface, main, pygame.Rect(TL_X0 - 14, int(y) + 4, 6, int(lane_h) - 8))
        _text(surface, settings.accounts[email].lane_label, 22, main, TL_X0 + 6, int(y) + 4)
        if i:
            pygame.draw.line(surface, theme.C["panel_line"], (TL_X0, y), (TL_X1, y))


def _render_now_line(surface, settings, now: datetime) -> None:
    start = now.replace(hour=settings.start_hour, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=settings.end_hour)
    if not (start <= now <= end):
        return
    x = time_to_x(now, now.date(), settings.start_hour, settings.end_hour, TL_X0, TL_X1)
    pygame.draw.line(surface, theme.C["now"], (x, 52), (x, 420), 3)
    img = theme.font(20).render(now.strftime("%H:%M"), True, theme.C["now_text"])
    r = img.get_rect(midtop=(x, 54))
    pygame.draw.rect(surface, theme.C["now"], r.inflate(12, 6), border_radius=4)
    surface.blit(img, r)
