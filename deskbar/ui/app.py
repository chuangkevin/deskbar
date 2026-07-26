import os
import sys
import traceback

import pygame

from deskbar import transform
from deskbar.layout import Rect
from deskbar.ui import Hit

LOGICAL_W, LOGICAL_H = 1920, 480
DRAG_THRESHOLD = 24                     # px，觸控拖曳判定門檻


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
        self.view_anchor = None         # datetime|None，None=跟隨現在
        self._drag_start = None         # 觸控/滑鼠按下時的邏輯座標 (x, y)
        self._drag_last = None          # 拖曳中累計的最新座標（供未來即時重繪擴充）
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
        from datetime import datetime, time as _time
        from zoneinfo import ZoneInfo
        from deskbar import sync
        from deskbar.ui import alarm_view, dashboard, detail, settings_view
        from deskbar.viewwin import clamp_anchor, next_span
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
                            try:
                                self.alarm_store.toggle(h.data)
                            except OSError as e:
                                print(f"[deskbar] alarm toggle write failed: {e}",
                                      file=sys.stderr)
                    elif a == "delete_alarm":
                        if self.alarm_store is not None:
                            try:
                                self.alarm_store.remove(h.data)
                            except OSError as e:
                                print(f"[deskbar] alarm delete write failed: {e}",
                                      file=sys.stderr)
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
                            try:
                                self.alarm_store.add("%02d:%02d" % (hh, mm), days, label)
                            except OSError as e:
                                print(f"[deskbar] alarm add write failed: {e}",
                                      file=sys.stderr)
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
                    elif a == "cycle_span":
                        self.settings.view_span = next_span(self.settings.view_span)
                        self.on_save(self.settings)
                    elif a == "cycle_view_mode":
                        self.settings.view_mode = (
                            "lanes" if self.settings.view_mode == "agenda" else "agenda")
                        self.on_save(self.settings)
                    elif a == "force_sync":
                        sync.request_sync()
                    elif a == "goto_now":
                        self.view_anchor = None
                    elif a == "goto_day":
                        tz = ZoneInfo("Asia/Taipei")
                        candidate = datetime.combine(h.data, _time(12, 0), tzinfo=tz)
                        # 月視圖已經只給窗口內的日子出 hit，這裡再夾一次是防禦性重複保險
                        # （和 _pan_view 用同一支 clamp_anchor，行為一致）。
                        self.view_anchor = clamp_anchor(candidate, datetime.now(tz), tz)
                        self.settings.view_span = "day"
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
        # sync 現在只在 phase (a) 短暫持鎖（微秒級），這裡加鎖不會再造成長時間凍結；
        # 反過來若不加鎖，sync 的 phase (a) 可能正好在改 settings.accounts 途中被讀到。
        # _dispatch 的 with self.lock: 區塊不會呼叫 _render，故這裡再取鎖不會死結。
        with self.lock:
            if self.view == "settings":
                self.hits = settings_view.render(self.logical, snap, self.settings,
                                                 self.confirm_remove)
            elif self.view == "alarms":
                self.hits = alarm_view.render(self.logical, self.alarm_store,
                                              self.alarm_draft, now)
            else:
                self.hits = dashboard.render(self.logical, snap, self.settings, now, clock_anim,
                                             anchor=self.view_anchor)
                if self.view == "detail" and self.detail_event is not None:
                    self.hits += detail.render(self.logical, self.detail_event)
        self._flip()
        self._last_seq = snap.seq
        self._last_minute = now.minute
        self._last_clock_text = now.strftime("%H:%M")

    def _handle_touch_up(self, x: int, y: int) -> None:
        """FINGERUP／MOUSEBUTTONUP 共用：判斷是點擊還是時間軸平移拖曳。"""
        if self._drag_start is None:
            self._dispatch(x, y)
            return
        sx, _sy = self._drag_start
        dx = x - sx
        self._drag_start = None
        from deskbar.ui.dashboard import TL_X0, TL_X1
        if abs(dx) > DRAG_THRESHOLD and sx > TL_X0:
            self._pan_view(dx, TL_X1 - TL_X0)
            self._last_seq = -1      # 放手後強制重繪
        else:
            self._dispatch(x, y)

    def _pan_view(self, dx_px: float, area_w: float) -> None:
        """時間軸拖曳平移錨點：向右拖＝看過去。範圍 clamp 在資料窗口 [今天-7, 今天+30]。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from deskbar.viewwin import clamp_anchor, view_window
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.now(tz)
        with self.lock:
            anchor_or_now = self.view_anchor if self.view_anchor is not None else now
            win_start, win_end = view_window(
                self.settings.view_span, anchor_or_now, tz,
                start_hour=self.settings.start_hour, end_hour=self.settings.end_hour)
            window_len = win_end - win_start
            shift = dx_px / area_w * window_len
            new_anchor = anchor_or_now - shift
            self.view_anchor = clamp_anchor(new_anchor, now, tz)

    def run(self) -> None:
        self._init_display()
        clock = pygame.time.Clock()
        self._render()
        running = True
        while running:
            try:
                running = self._run_iteration(clock, running)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                # 單一畫格出錯不該弄死整個常駐程式（systemd 重啟＝鬧鐘頁永久壞掉）。
                # 只記錄、降級這一格，下一圈繼續跑。
                traceback.print_exc(file=sys.stderr)
                clock.tick(10)
        pygame.quit()

    def _run_iteration(self, clock, running: bool) -> bool:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
            elif ev.type == pygame.FINGERDOWN:
                x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                self._drag_start = (x, y)
                self._drag_last = (x, y)
            elif ev.type == pygame.FINGERMOTION:
                if self._drag_start is not None:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self._drag_last = (x, y)
            elif ev.type == pygame.FINGERUP:
                x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                self._handle_touch_up(x, y)
            elif ev.type == pygame.MOUSEBUTTONDOWN:   # dev 模式滑鼠模擬觸控
                nx = ev.pos[0] / max(1, self.win[0] - 1)
                ny = ev.pos[1] / max(1, self.win[1] - 1)
                x, y = transform.touch_to_logical(nx, ny, self.settings.rotation)
                self._drag_start = (x, y)
                self._drag_last = (x, y)
            elif ev.type == pygame.MOUSEMOTION:
                if self._drag_start is not None:
                    nx = ev.pos[0] / max(1, self.win[0] - 1)
                    ny = ev.pos[1] / max(1, self.win[1] - 1)
                    x, y = transform.touch_to_logical(nx, ny, self.settings.rotation)
                    self._drag_last = (x, y)
            elif ev.type == pygame.MOUSEBUTTONUP:
                nx = ev.pos[0] / max(1, self.win[0] - 1)
                ny = ev.pos[1] / max(1, self.win[1] - 1)
                x, y = transform.touch_to_logical(nx, ny, self.settings.rotation)
                self._handle_touch_up(x, y)
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
            self._anim_start = None
            self._render()          # 閃爍需每圈重繪
            clock.tick(10)
            return running
        # 翻牌動畫（30fps 燒 400ms）只在 dashboard 頁才有意義；離開 dashboard 就不該
        # 燒 CPU（1GHz 的 Pi Zero 2 W 上，設定/鬧鐘頁跑這個純屬浪費）。
        animating = self.view == "dashboard" and not self.firing
        if not animating and self._anim_start is not None:
            self._anim_start = None
        if animating and self._anim_start is None and now.minute != self._last_minute \
                and self._last_clock_text is not None:
            self._clock_prev = self._last_clock_text
            self._anim_start = time.monotonic()
        if animating and self._anim_start is not None:
            progress = min(1.0, (time.monotonic() - self._anim_start) / 0.4)
            self._render(clock_anim=(self._clock_prev, progress))
            if progress >= 1.0:
                self._anim_start = None
            clock.tick(30)
        else:
            if self.state.snapshot().seq != self._last_seq or now.minute != self._last_minute:
                self._render()
            clock.tick(10)
        return running
