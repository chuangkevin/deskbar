import os

import pygame

from deskbar import transform
from deskbar.layout import Rect
from deskbar.ui import Hit

LOGICAL_W, LOGICAL_H = 1920, 480


class App:
    def __init__(self, state, settings, settings_lock, on_save, alarm_store=None):
        self.state = state
        self.settings = settings
        self.lock = settings_lock
        self.on_save = on_save          # callable：settings 變更後持久化
        self.view = "dashboard"         # dashboard | settings | detail | alarms
        self.detail_event = None
        self.hits: list[Hit] = []
        self._last_seq = -1
        self._last_minute = None
        self._last_clock_text = None
        self._clock_prev = None
        self._anim_start = None
        self.alarm_store = alarm_store
        self.firing = []
        self._last_alarm_check = None
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        self.alarm_draft = {"hour": (now.hour + 1) % 24, "minute": 0, "days": set(),
                             "label_idx": 0}

    def _init_display(self) -> None:
        if os.environ.get("DESKBAR_DEV") != "1":
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        pygame.init()
        flags = 0 if os.environ.get("DESKBAR_DEV") == "1" else pygame.FULLSCREEN
        if os.environ.get("DESKBAR_DEV") == "1":
            scale = float(os.environ.get("DESKBAR_DEV_SCALE", "0.45"))
            self.win = (round(transform.NATIVE_W * scale), round(transform.NATIVE_H * scale))
        else:
            self.win = (transform.NATIVE_W, transform.NATIVE_H)
        self.screen = pygame.display.set_mode(self.win, flags)
        pygame.display.set_caption("deskbar")
        pygame.mouse.set_visible(False)
        self.logical = pygame.Surface((LOGICAL_W, LOGICAL_H))

    def _flip(self) -> None:
        angle = transform.pygame_rotation_angle(self.settings.rotation)
        rotated = pygame.transform.rotate(self.logical, angle)
        if self.win != (transform.NATIVE_W, transform.NATIVE_H):
            rotated = pygame.transform.smoothscale(rotated, self.win)
        self.screen.blit(rotated, (0, 0))
        pygame.display.flip()

    def _dispatch(self, x: int, y: int) -> None:
        from deskbar.ui import alarm_view, dashboard, detail, settings_view
        for h in reversed(self.hits):   # 上層優先
            if h.rect.contains(x, y):
                a = h.action
                if a == "noop":
                    return
                if a == "dismiss_alarm":
                    self.firing and self.firing.pop(0)
                    self._last_seq = -1
                    return
                with self.lock:
                    if a == "open_settings":
                        self.view = "settings"
                    elif a == "open_alarms":
                        self.view = "alarms"
                    elif a == "open_detail":
                        self.view, self.detail_event = "detail", h.data
                    elif a in ("close", "settings_done"):
                        self.view = "dashboard"
                    elif a == "toggle_alarm":
                        if self.alarm_store is not None:
                            current = next((al.enabled for al in self.alarm_store.list()
                                             if al.id == h.data), None)
                            if current is not None:
                                self.alarm_store.set_enabled(h.data, not current)
                    elif a == "delete_alarm":
                        if self.alarm_store is not None:
                            self.alarm_store.remove(h.data)
                    elif a == "draft_hour":
                        alarm_view.bump_draft(self.alarm_draft, "hour", h.data)
                    elif a == "draft_minute":
                        alarm_view.bump_draft(self.alarm_draft, "minute", h.data)
                    elif a == "draft_day":
                        alarm_view.bump_draft(self.alarm_draft, "day", h.data)
                    elif a == "draft_label":
                        alarm_view.bump_draft(self.alarm_draft, "label", h.data)
                    elif a == "add_alarm":
                        if self.alarm_store is not None:
                            hh, mm = self.alarm_draft["hour"], self.alarm_draft["minute"]
                            days = sorted(self.alarm_draft["days"])
                            label = alarm_view.LABELS[self.alarm_draft["label_idx"]]
                            self.alarm_store.add("%02d:%02d" % (hh, mm), days, label)
                            self.alarm_draft["days"] = set()
                    elif a == "toggle_cal":
                        email, cal = h.data
                        cals = self.settings.accounts[email].calendars
                        cals[cal] = not cals[cal]
                        self.on_save(self.settings)
                    elif a == "cycle_label":
                        email = h.data
                        acc = self.settings.accounts[email]
                        presets = ["工作", "個人", "家庭", email.split("@")[0]]
                        i = (presets.index(acc.lane_label) + 1) if acc.lane_label in presets else 0
                        acc.lane_label = presets[i % len(presets)]
                        self.on_save(self.settings)
                    elif a == "rotate":
                        self.settings.rotation = 270 if self.settings.rotation == 90 else 90
                        self.on_save(self.settings)
                    elif a == "remove_account":
                        self.confirm_remove = h.data   # email；settings_view 畫二次確認
                    elif a == "confirm_remove":
                        email = h.data
                        from deskbar import config as cfg
                        for p in cfg.accounts_dir().glob("*.json"):
                            import json as _json
                            try:
                                if _json.loads(p.read_text(encoding="utf-8")).get("email") == email:
                                    p.unlink()
                            except (OSError, ValueError):
                                pass
                        self.settings.accounts.pop(email, None)
                        self.state.drop_account(email)
                        self.on_save(self.settings)
                        self.confirm_remove = None
                self._last_seq = -1     # 強制重繪
                return

    confirm_remove = None

    def _render(self, clock_anim=None) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from deskbar.ui import alarm_overlay, alarm_view, dashboard, detail, settings_view
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        if self.firing:
            self.hits = alarm_overlay.render(self.logical, self.firing[0], now)
            self._flip()
            return
        snap = self.state.snapshot()
        self.logical.fill((15, 15, 15))
        if self.view == "settings":
            self.hits = settings_view.render(self.logical, snap, self.settings,
                                             self.confirm_remove)
        elif self.view == "alarms":
            self.hits = alarm_view.render(self.logical, self.alarm_store,
                                          self.alarm_draft, now)
        else:
            self.hits = dashboard.render(self.logical, snap, self.settings, now, clock_anim)
            if self.view == "detail" and self.detail_event is not None:
                self.hits += detail.render(self.logical, self.detail_event)
        self._flip()
        self._last_seq = snap.seq
        self._last_minute = now.minute
        self._last_clock_text = now.strftime("%H:%M")

    def run(self) -> None:
        self._init_display()
        clock = pygame.time.Clock()
        self._render()
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif ev.type == pygame.FINGERDOWN:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self._dispatch(x, y)
                elif ev.type == pygame.MOUSEBUTTONDOWN:   # dev 模式滑鼠模擬觸控
                    nx = ev.pos[0] / max(1, self.win[0] - 1)
                    ny = ev.pos[1] / max(1, self.win[1] - 1)
                    x, y = transform.touch_to_logical(nx, ny, self.settings.rotation)
                    self._dispatch(x, y)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            import time
            now = datetime.now(ZoneInfo("Asia/Taipei"))
            if self.alarm_store is not None:
                due = self.alarm_store.due(self._last_alarm_check, now)
                self._last_alarm_check = now
                if due:
                    self.firing.extend(due)
                    self._last_seq = -1
            if self.firing:
                self._render()          # 閃爍需每圈重繪
                clock.tick(10)
                continue
            if self._anim_start is None and now.minute != self._last_minute \
                    and self._last_clock_text is not None:
                self._clock_prev = self._last_clock_text
                self._anim_start = time.monotonic()
            if self._anim_start is not None:
                progress = min(1.0, (time.monotonic() - self._anim_start) / 0.4)
                self._render(clock_anim=(self._clock_prev, progress))
                if progress >= 1.0:
                    self._anim_start = None
                clock.tick(30)
            else:
                if self.state.snapshot().seq != self._last_seq or now.minute != self._last_minute:
                    self._render()
                clock.tick(10)
        pygame.quit()
