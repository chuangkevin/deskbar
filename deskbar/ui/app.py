import os
import sys
import time
import traceback

import pygame

from deskbar import transform
from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme
from deskbar.ui.transitions import SlideTransition

LOGICAL_W, LOGICAL_H = 1920, 480
DRAG_THRESHOLD = 24                     # px，觸控拖曳判定門檻
SYNC_INTERVALS = [1, 3, 5, 10, 30]       # 設定頁「同步頻率」鈕的循環清單（分鐘）
# 氛圍幀率不是常數：由 weatherfx.ambient_fps(code) 分級（雨/雷 15、雪 12、
# 晴/雲/霧 8）——實務上 open-meteo 的每個 code 都有動態場景，氛圍模式是 24/7
# 常態，分級幀率才是 Pi Zero 2W 上真正的省電槓桿。


class App:
    def __init__(self, state, settings, settings_lock, on_save, alarm_store=None):
        self.state = state
        self.settings = settings
        self.lock = settings_lock
        self.on_save = on_save          # callable：settings 變更後持久化
        self.view = "dashboard"         # dashboard | settings | detail | alarms | wifi
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
        self._transition = SlideTransition()   # 切換過場：舊/新畫面滑動合成
        self._transition_start = None   # time.monotonic()，None＝沒在跑過場
        self._last_imminent_check = None  # 迫近行程：上次檢查時間（每秒檢查一次即可）
        self._imminent_active = False     # 迫近行程：本秒是否有迫近中的行程
        self._weather_epoch = time.monotonic()   # 天氣場景時間基準：t＝距開機浮點秒數
        from deskbar.ui import wifi_view
        self.wifi_ui = wifi_view.new_state()     # Wi-Fi 設定頁狀態（背景執行緒共寫）
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        self.alarm_draft = {"hour": (now.hour + 1) % 24, "minute": 0, "days": set(),
                             "label_idx": 0}

    def _init_display(self) -> None:
        self._dev = os.environ.get("DESKBAR_DEV") == "1"
        if not self._dev:
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        pygame.init()
        flags = 0 if self._dev else pygame.FULLSCREEN
        if self._dev:
            # dev 外層旋轉（Mac 上看畫面用）：0/180＝橫向轉正（能看全景、預設）、
            # 90/270＝模擬實機直立面板。與實機的 settings.rotation 管線無關，
            # 純粹是「Mac 視窗要怎麼擺給人看」。視窗內按 R 鍵循環。
            self._dev_rotate = int(os.environ.get("DESKBAR_DEV_ROTATE", "0")) % 360
            self._dev_scale = float(os.environ.get("DESKBAR_DEV_SCALE", "0.6"))
            self._apply_dev_window()
        else:
            self._dev_rotate = None
            self.win = (transform.NATIVE_W, transform.NATIVE_H)
            self.screen = pygame.display.set_mode(self.win, flags)
        pygame.display.set_caption("deskbar")
        pygame.mouse.set_visible(self._dev)
        self.logical = pygame.Surface((LOGICAL_W, LOGICAL_H))

    def _apply_dev_window(self) -> None:
        s = self._dev_scale
        if self._dev_rotate in (0, 180):
            self.win = (round(LOGICAL_W * s), round(LOGICAL_H * s))
        else:
            self.win = (round(LOGICAL_H * s), round(LOGICAL_W * s))
        self.screen = pygame.display.set_mode(self.win, 0)

    def _cycle_dev_rotate(self) -> None:
        if not self._dev:
            return
        self._dev_rotate = (self._dev_rotate + 90) % 360
        self._apply_dev_window()
        self._last_seq = -1     # 立即重繪

    def _flip(self) -> None:
        if self._dev:
            # dev：外層旋轉直接作用在邏輯畫面上（0=轉正全景），不經實機面板管線
            out = self.logical if self._dev_rotate == 0 \
                else pygame.transform.rotate(self.logical, -self._dev_rotate)
            out = pygame.transform.smoothscale(out, self.win)
            self.screen.blit(out, (0, 0))
        else:
            angle = transform.pygame_rotation_angle(self.settings.rotation)
            rotated = pygame.transform.rotate(self.logical, angle)
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
                    elif a == "open_wifi":
                        self.view = "wifi"
                        self._wifi_rescan()
                    elif a == "wifi_back":
                        self.view = "settings"
                        self.wifi_ui["msg"] = ""
                    elif a == "wifi_rescan":
                        self._wifi_rescan()
                    elif a == "wifi_pick":
                        net = h.data
                        if net.active:
                            # 點目前連線中的網路＝無事可做；真的去 connect 會讓
                            # nmcli 重新關聯、整台瞬斷（實機首日踩到）。
                            self.wifi_ui["msg"] = f"已連線 {net.ssid}"
                        elif net.secured and not net.known:
                            self.wifi_ui.update(phase="password", selected=net.ssid,
                                                selected_secured=True,
                                                selected_security=net.security,
                                                pw="", msg="",
                                                shift=False, sym=False, show_pw=False)
                        else:
                            self._wifi_connect(net.ssid, None, net.security)
                    elif a == "wifi_key":
                        from deskbar.ui import wifi_view
                        if len(self.wifi_ui["pw"]) < wifi_view.PW_MAX:
                            self.wifi_ui["pw"] += h.data
                    elif a == "wifi_backspace":
                        self.wifi_ui["pw"] = self.wifi_ui["pw"][:-1]
                    elif a == "wifi_shift":
                        self.wifi_ui["shift"] = not self.wifi_ui["shift"]
                    elif a == "wifi_sym":
                        self.wifi_ui["sym"] = not self.wifi_ui["sym"]
                    elif a == "wifi_show":
                        self.wifi_ui["show_pw"] = not self.wifi_ui["show_pw"]
                    elif a == "wifi_cancel":
                        self.wifi_ui.update(phase="list", pw="", msg="")
                    elif a == "wifi_connect":
                        if self.wifi_ui["pw"]:
                            self._wifi_connect(self.wifi_ui["selected"],
                                               self.wifi_ui["pw"],
                                               self.wifi_ui.get("selected_security", ""))
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
                    elif a == "toggle_presence":
                        self.settings.presence_enabled = not self.settings.presence_enabled
                        self.on_save(self.settings)
                    elif a == "cycle_presence_speed":
                        # 快=15s 探測/45s 緩衝、中=30/90、慢=45/150（預設）。
                        # 離場感知延遲 ≈ 間隔 + 緩衝，回場 ≈ 一個間隔。
                        presets = [(15, 45), (30, 90), (45, 150)]
                        cur = (self.settings.presence_interval_sec,
                               self.settings.presence_grace_sec)
                        idx = presets.index(cur) if cur in presets else -1
                        nxt = presets[(idx + 1) % len(presets)]
                        self.settings.presence_interval_sec = nxt[0]
                        self.settings.presence_grace_sec = nxt[1]
                        self.on_save(self.settings)
                    elif a == "cycle_theme":
                        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
                        theme.set_theme(self.settings.theme)
                        self.on_save(self.settings)
                    elif a == "cycle_span":
                        self._start_transition()
                        self.settings.view_span = next_span(self.settings.view_span)
                        self.on_save(self.settings)
                    elif a == "cycle_view_mode":
                        self._start_transition()
                        self.settings.view_mode = (
                            "lanes" if self.settings.view_mode == "agenda" else "agenda")
                        self.on_save(self.settings)
                    elif a == "force_sync":
                        sync.request_sync()
                    elif a == "goto_now":
                        self._start_transition()
                        self.view_anchor = None
                    elif a == "goto_day":
                        self._start_transition()
                        tz = ZoneInfo("Asia/Taipei")
                        candidate = datetime.combine(h.data, _time(12, 0), tzinfo=tz)
                        # 月視圖已經只給窗口內的日子出 hit，這裡再夾一次是防禦性重複保險
                        # （和 _pan_view 用同一支 clamp_anchor，行為一致）。
                        self.view_anchor = clamp_anchor(candidate, datetime.now(tz), tz)
                        self.settings.view_span = "day"
                        self.on_save(self.settings)
                    elif a == "cycle_sync_interval":
                        cur = self.settings.sync_interval_min
                        i = SYNC_INTERVALS.index(cur) if cur in SYNC_INTERVALS else -1
                        self.settings.sync_interval_min = SYNC_INTERVALS[
                            (i + 1) % len(SYNC_INTERVALS)]
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

    def _draw_frame(self, snap, now, clock_anim=None) -> None:
        """把目前 view 畫進 self.logical（不 flip、不動 _last_* 記帳）。
        拆出這支給 _render()（正常重繪）與 _render_transition_frame()（切換過場，
        還要在這之上疊一層舊畫面滑出效果）共用。"""
        from deskbar.ui import alarm_view, dashboard, detail, settings_view
        self.logical.fill(theme.C["bg"])
        # sync 現在只在 phase (a) 短暫持鎖（微秒級），這裡加鎖不會再造成長時間凍結；
        # 反過來若不加鎖，sync 的 phase (a) 可能正好在改 settings.accounts 途中被讀到。
        # _dispatch 的 with self.lock: 區塊不會呼叫 _render，故這裡再取鎖不會死結。
        with self.lock:
            if self.view == "settings":
                self.hits = settings_view.render(self.logical, snap, self.settings,
                                                 self.confirm_remove)
            elif self.view == "wifi":
                from deskbar.ui import wifi_view
                self.hits = wifi_view.render(self.logical, self.wifi_ui, now)
            elif self.view == "alarms":
                self.hits = alarm_view.render(self.logical, self.alarm_store,
                                              self.alarm_draft, now)
            else:
                self.hits = dashboard.render(self.logical, snap, self.settings, now, clock_anim,
                                             anchor=self.view_anchor,
                                             weather_t=self._weather_t())
                if self.view == "detail" and self.detail_event is not None:
                    self.hits += detail.render(self.logical, self.detail_event)

    def _wifi_rescan(self) -> None:
        """背景掃描：nmcli 最長可跑 20 秒，不能擋 render loop。單寫者模式：
        busy 旗標保證同時只有一條 Wi-Fi 執行緒在寫 wifi_ui。"""
        ui = self.wifi_ui
        if ui["busy"]:
            return
        ui["busy"] = "scan"
        import threading
        from deskbar import wifi

        def work():
            nets = wifi.scan()
            ui["nets"] = nets
            ui["active"] = wifi.active_info()
            ui["busy"] = None

        threading.Thread(target=work, daemon=True, name="wifi-scan").start()

    def _wifi_connect(self, ssid: str, password, security: str = "") -> None:
        """背景連線（nmcli 最長 60 秒）。成功→清密碼、回列表、重掃；
        失敗→留在原畫面顯示原因讓使用者改密碼重試。"""
        ui = self.wifi_ui
        if ui["busy"]:
            return
        ui["busy"] = "connect"
        ui["selected"] = ssid
        ui["msg"] = ""
        import threading
        from deskbar import wifi

        def work():
            ok, msg = wifi.connect(ssid, password, security)
            if ok:
                ui.update(phase="list", pw="", msg=f"已連線 {ssid}")
                ui["nets"] = wifi.scan()
                ui["active"] = wifi.active_info()
            elif password is None:
                # 「已儲存」網路用舊 profile 連失敗（密碼改了/profile 壞了）：
                # 直接彈密碼鍵盤讓使用者重新輸入，而不是卡在清單反覆失敗。
                ui.update(phase="password", selected=ssid, selected_secured=True,
                          pw="", shift=False, sym=False, show_pw=False,
                          msg=f"連線失敗：{msg}｜請輸入密碼重試")
            else:
                ui["msg"] = f"連線失敗：{msg}"
            ui["busy"] = None

        threading.Thread(target=work, daemon=True, name="wifi-connect").start()

    def _weather_t(self) -> float:
        """天氣場景的浮點秒數（單調時鐘，不受對時跳動影響）。weatherfx 全部速度
        以 px/秒 定義，重繪頻率快慢只影響流暢度、不影響移動速率。"""
        return time.monotonic() - self._weather_epoch

    def _ambient_active(self, snap) -> bool:
        """天氣場景是否需要逐幀重繪：只在 dashboard 本頁（detail/settings/alarms
        都不跑——modal 開著就讓背景靜止，跟過場/翻牌互斥的既有邏輯一致）、沒有
        鬧鐘在響、且有天氣資料時成立。ANIMATED_CODES 是對「未知 code」的防禦
        閘門而非省電機制——open-meteo 正常會回的 code 全在裡面，氛圍模式實務上
        是 24/7 常態；真正的省電槓桿是 weatherfx.ambient_fps() 的分級幀率。"""
        if self.view != "dashboard" or self.firing:
            return False
        if snap.weather is None:
            return False
        from deskbar.ui import weatherfx
        return snap.weather.code in weatherfx.ANIMATED_CODES

    def _render_ambient(self, snap, now) -> None:
        """氛圍幀：資料/分鐘都沒變時，只重畫左欄（時鐘/天氣場景）再合成輸出，
        不重算中欄行事曆與右欄油表——Pi Zero 2W 燒不起整面 15fps 全量重繪。
        不動 hits、不動 _last_* 記帳：這一幀對「什麼時候需要全量重繪」的判斷
        完全透明。"""
        with self.lock:
            from deskbar.ui import dashboard
            dashboard.render_panel_only(self.logical, snap, self.settings, now,
                                        self._weather_t())
        self._flip()

    def _render(self, clock_anim=None) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from deskbar.ui import alarm_overlay
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        if self.firing:
            self.hits = alarm_overlay.render(self.logical, self.firing[0], now)
            self._flip()
            return
        snap = self.state.snapshot()
        self._draw_frame(snap, now, clock_anim)
        self._flip()
        self._last_seq = snap.seq
        self._last_minute = now.minute
        self._last_clock_text = now.strftime("%H:%M")

    def _start_transition(self, direction: int = 1) -> None:
        """cycle_span/cycle_view_mode/goto_now/goto_day 觸發時呼叫：把「現在畫面」交給
        SlideTransition 存成過場素材。沒有真的顯示器時（測試直接呼叫 _dispatch，不經
        _init_display）self.logical 不存在，直接跳過——過場只是視覺加分，不該讓沒有畫面
        可存的呼叫端炸掉。direction>=0：舊畫面往左滑出／新畫面從右側滑入（前進）；
        direction<0：方向相反（後退）。
        """
        logical = getattr(self, "logical", None)
        if logical is not None:
            import time
            self._transition.start(logical, direction)
            self._transition_start = time.monotonic()

    def _render_transition_frame(self, now) -> None:
        """切換過場的其中一幀：先照常畫「新」畫面進 self.logical，再交給 SlideTransition
        依實際經過秒數合成舊畫面滑出的效果；超過 DURATION（0.2s）後直接使用新畫面本身，
        過場結束。"""
        import time
        snap = self.state.snapshot()
        self._draw_frame(snap, now)
        elapsed = time.monotonic() - self._transition_start
        composed = self._transition.frame(self.logical, elapsed)
        if composed is not self.logical:
            self.logical.blit(composed, (0, 0))
        self._flip()
        self._last_seq = snap.seq
        self._last_minute = now.minute
        self._last_clock_text = now.strftime("%H:%M")
        if not self._transition.active():
            self._transition_start = None

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
        """時間軸拖曳平移錨點：向右拖＝看過去。範圍 clamp 在資料窗口 [今天-7, 今天+30]。

        v4.1：agenda 模式恢復可平移（fixwave2 曾整個關閉），但單位是「天」而非
        連續時間比例——dx 除以欄寬換算成天數、四捨五入，非零位移至少平移 1 天
        （欄寬本身可能遠大於 24px 拖曳判定門檻，四捨五入到 0 會讓拖曳看起來沒反應）。
        lanes 模式維持原本按時間比例的連續平移，行為不變。"""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from deskbar.viewwin import agenda_window, clamp_anchor, view_window
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.now(tz)
        with self.lock:
            anchor_or_now = self.view_anchor if self.view_anchor is not None else now
            if self.settings.view_mode == "agenda":
                _start, n_days = agenda_window(self.settings.view_span, anchor_or_now, tz)
                col_w = area_w / max(1, n_days)
                raw_days = dx_px / col_w if col_w else 0.0
                days = round(raw_days)
                if days == 0 and raw_days != 0:
                    days = 1 if raw_days > 0 else -1
                new_anchor = anchor_or_now - timedelta(days=days)
            else:
                win_start, win_end = view_window(
                    self.settings.view_span, anchor_or_now, tz,
                    start_hour=self.settings.start_hour, end_hour=self.settings.end_hour)
                window_len = win_end - win_start
                shift = dx_px / area_w * window_len
                new_anchor = anchor_or_now - shift
            self.view_anchor = clamp_anchor(new_anchor, now, tz)

    def _play_splash(self) -> None:
        """開機播一次 deskbar 掃光 splash（13 張 × 60ms ≈ 0.78s）；
        DESKBAR_NO_SPLASH=1 時跳過（開發/測試模式用，避免每次重開發流程都要等）。"""
        if os.environ.get("DESKBAR_NO_SPLASH") == "1":
            return
        from deskbar.ui import transitions
        for frame in transitions.splash_frames(LOGICAL_W, LOGICAL_H):
            self.logical.blit(frame, (0, 0))
            self._flip()
            pygame.event.pump()      # 避免視窗管理器誤判成無回應
            pygame.time.delay(60)

    def run(self) -> None:
        self._init_display()
        self._play_splash()
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
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_r:
                self._cycle_dev_rotate()
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
                x, y = transform.dev_window_to_logical(
                    ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                self._drag_start = (x, y)
                self._drag_last = (x, y)
            elif ev.type == pygame.MOUSEMOTION:
                if self._drag_start is not None:
                    x, y = transform.dev_window_to_logical(
                        ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                    self._drag_last = (x, y)
            elif ev.type == pygame.MOUSEBUTTONUP:
                x, y = transform.dev_window_to_logical(
                    ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                self._handle_touch_up(x, y)
        from datetime import datetime
        from zoneinfo import ZoneInfo
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
        if self._transition_start is not None:    # 切換過場優先於翻牌動畫（兩者不會同時發生）
            self._render_transition_frame(now)
            clock.tick(30)
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
            snap = self.state.snapshot()
            if self.view == "wifi":
                # Wi-Fi 頁固定 5fps 重繪：掃描/連線結束由背景執行緒改 wifi_ui，
                # 沒有 seq 可觸發，低頻輪詢重繪畫面自然跟上（含連線中的動態點點）。
                self._render()
                clock.tick(5)
            elif snap.seq != self._last_seq or now.minute != self._last_minute:
                self._render()
                clock.tick(10)
            elif self._ambient_active(snap):
                # 資料/分鐘都沒變，但天氣場景要動：左欄局部重繪，幀率按場景分級。
                # 歷史教訓（2026-07-27「根本看不到動畫」）：這裡以前只有上面那條
                # 全量重繪，天氣 tick 每秒都在加、畫面卻一分鐘才畫一次。
                self._render_ambient(snap, now)
                from deskbar.ui import weatherfx
                clock.tick(weatherfx.ambient_fps(snap.weather.code))
            else:
                clock.tick(10)
        return running
