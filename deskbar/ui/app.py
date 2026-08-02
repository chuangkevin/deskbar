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
WAKE_SECONDS = 30                        # 深夜熄屏中觸摸喚醒的持續秒數
ALARM_AUTO_DISMISS_S = 300               # 響鈴 5 分鐘沒人理＝自動解除（不然閃一整晚）
AUTO_SWITCH_BEFORE_MIN = 15              # 迫近行程搶焦點：開始前 N 分鐘自動切回行事曆
PAN_BAND_INTERVAL = 1 / 30               # 跟手位移的 flip 節流（帶狀 blit 很便宜，30fps 上限即可）
# 氛圍幀率不是常數：由 weatherfx.ambient_fps(code) 分級（雨/雷 15、雪 12、
# 晴/雲/霧 8）——實務上 open-meteo 的每個 code 都有動態場景，氛圍模式是 24/7
# 常態，分級幀率才是 Pi Zero 2W 上真正的省電槓桿。


class App:
    def __init__(self, state, settings, settings_lock, on_save, alarm_store=None,
                 notes_store=None, shot_bridge=None):
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
        self.notes_store = notes_store
        from deskbar.ui import notesview
        self.notes_ui = notesview.new_state()
        self.firing = []
        self._firing_since = 0.0        # 最近一顆鬧鐘開始響的時刻（自動解除計時基準）
        self._last_alarm_check = None
        self.view_anchor = None         # datetime|None，None=跟隨現在
        self._drag_start = None         # 觸控/滑鼠按下時的邏輯座標 (x, y)
        self._drag_last = None          # 拖曳中累計的最新座標（供未來即時重繪擴充）
        self._transition = SlideTransition()   # 切換過場：舊/新畫面滑動合成
        self._transition_start = None   # time.monotonic()，None＝沒在跑過場
        self._last_imminent_check = None  # 迫近行程：上次檢查時間（每秒檢查一次即可）
        self._imminent_active = False     # 迫近行程：本秒是否有迫近中的行程
        self._weather_epoch = time.monotonic()   # 天氣場景時間基準：t＝距開機浮點秒數
        from deskbar.ui import bt_view, wifi_view
        self.wifi_ui = wifi_view.new_state()     # Wi-Fi 設定頁狀態（背景執行緒共寫）
        self.bt_ui = bt_view.new_state()         # 藍牙配對頁狀態（背景執行緒共寫）
        self._veil = None                        # 亮度疊黑快取：(size, alpha, surface)
        self.center_pages = {"linear": 0, "notes": 0}   # 待辦/便條牆目前頁碼（滑動翻頁）
        self.shot_bridge = shot_bridge  # /api/screenshot 的跨執行緒橋（want/done/data）
        self._pressed_dirty = False     # 按壓高亮畫上去了，放手後要洗掉
        self._wake_until = 0.0          # 熄屏觸摸喚醒的截止時刻（monotonic）
        self._swallow_touch = False     # 熄屏中的第一觸＝喚醒，不當作操作
        self._pan_band = None           # 跟手拖曳：中欄帶狀快照（拖曳中 1:1 位移，放手清除）
        self._pan_band_at = 0.0
        self._transition_cache = None   # 過場期間的「新畫面」快照：只算一次，逐幀純合成
        self._rot_cache = None          # 實機旋轉輸出快取：髒區域局部旋轉的基底
        self._rot_angle = None
        self._auto_center_prev = None   # 迫近行程自動切回行事曆前，使用者原本的中欄視圖
        self._auto_center_hold = False  # 使用者在迫近期間手動切走＝這一波不再搶（實機回報：看便條被踢回）
        self._auto_center_check_at = 0.0
        self.card_overlay = None        # 待辦卡詳情浮層（LinearIssue|None）
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

    def _dim_veil(self, size) -> "pygame.Surface | None":
        """亮度排程的疊黑面。必須蓋在「輸出面」（每幀新製的 rotated/out），
        不能蓋 logical——氛圍幀只重畫左欄，蓋持久畫布會讓其餘區域逐幀重複
        疊黑越來越暗。veil 依 (size, alpha) 快取，亮度沒變就零成本。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from deskbar import brightness
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        pct = brightness.effective(self.settings, now.hour * 60 + now.minute,
                                   awake=bool(self.firing)
                                   or time.monotonic() < self._wake_until)
        alpha = brightness.veil_alpha(pct)
        if alpha <= 0:
            return None
        if self._veil is None or self._veil[0] != size or self._veil[1] != alpha:
            s = pygame.Surface(size, pygame.SRCALPHA)
            s.fill((0, 0, 0, alpha))
            self._veil = (size, alpha, s)
        return self._veil[2]

    @staticmethod
    def _map_rot(r: "pygame.Rect", angle: int, lw: int = LOGICAL_W,
                 lh: int = LOGICAL_H) -> tuple:
        """logical 上的矩形 r 旋轉 angle 後，在旋轉輸出面上的左上角座標。
        只支援實機的兩個角度（rotation=90→-90、rotation=270→+90）；映射
        正確性由 test_flip_dirty_rotation_matches_full 逐 byte 鎖定。"""
        if angle % 360 == 270:          # pygame.rotate(-90)＝順時針
            return (lh - r.y - r.h, r.x)
        return (r.y, lw - r.x - r.w)    # +90＝逆時針

    def _flip(self, dirty=None) -> None:
        """dirty（logical 座標的 Rect|tuple|None）：這一幀只有該區域變了。
        實機路徑據此只旋轉髒區域、貼回持久的旋轉快取——整張 1920×480 旋轉
        （92 萬像素）是每幀固定稅，氛圍幀只動左欄(400 寬)、拖曳只動中欄，
        局部旋轉把這筆稅砍到 1/5～1/2（實機 70% CPU 的主成分）。
        亮度疊黑改蓋在 screen 上，旋轉快取永遠保持乾淨原圖。"""
        if self._dev:
            # dev：外層旋轉直接作用在邏輯畫面上（0=轉正全景），不經實機面板管線
            out = self.logical if self._dev_rotate == 0 \
                else pygame.transform.rotate(self.logical, -self._dev_rotate)
            out = pygame.transform.smoothscale(out, self.win)
            veil = self._dim_veil(out.get_size())
            if veil is not None:
                out.blit(veil, (0, 0))
            self.screen.blit(out, (0, 0))
        else:
            angle = transform.pygame_rotation_angle(self.settings.rotation)
            if self._rot_cache is None or self._rot_angle != angle or dirty is None:
                self._rot_cache = pygame.transform.rotate(self.logical, angle)
                self._rot_angle = angle
            else:
                r = pygame.Rect(dirty).clip(self.logical.get_rect())
                if r.w > 0 and r.h > 0:
                    sub = pygame.transform.rotate(self.logical.subsurface(r), angle)
                    self._rot_cache.blit(sub, self._map_rot(r, angle))
            self.screen.blit(self._rot_cache, (0, 0))
            veil = self._dim_veil(self._rot_cache.get_size())
            if veil is not None:
                self.screen.blit(veil, (0, 0))
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
                    elif a == "open_screen":
                        self.view = "screen"
                    elif a == "toggle_sleep":
                        self.settings.sleep_enabled = not self.settings.sleep_enabled
                        self.on_save(self.settings)
                    elif a == "linear_detail":
                        self.card_overlay = h.data
                    elif a == "overlay_close":
                        self.card_overlay = None
                    elif a == "scr_adj":
                        field, delta, lo, hi = h.data
                        cur = getattr(self.settings, field)
                        setattr(self.settings, field,
                                max(lo, min(hi, cur + delta)))
                        self.on_save(self.settings)
                    elif a == "open_bt":
                        self.view = "bt"
                        self._bt_rescan()
                    elif a == "bt_rescan":
                        self._bt_rescan()
                    elif a == "bt_pick":
                        self._bt_pick(h.data)
                    elif a == "bt_unpair":
                        self._bt_unpair(h.data)
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
                    elif a == "toggle_center":
                        self._start_transition()
                        order = ["calendar", "linear", "notes"]
                        cur = getattr(self.settings, "center_view", "calendar")
                        idx = order.index(cur) if cur in order else 0
                        self.settings.center_view = order[(idx + 1) % len(order)]
                        self.center_pages = {"linear": 0, "notes": 0}
                        # 使用者手動切換＝接管：取消還原、且這一波迫近期間不再搶焦點
                        # （沒 hold 的話 5 秒後又被抓回行事曆——本機測試實測踩到）
                        self._auto_center_prev = None
                        self._auto_center_hold = True
                        self.card_overlay = None
                        self.on_save(self.settings)
                    elif a == "note_arm":
                        # 撕除第一段：整卡點一下＝武裝（出現 ✕ 鈕）。第二段
                        # 必須點中 ✕ 小目標（note_del），點卡上其他地方＝取消
                        # ——舊版兩段都是整卡目標，連點兩下就誤撕
                        self.notes_ui["pending_id"] = h.data
                        self.notes_ui["pending_at"] = time.monotonic()
                    elif a == "note_cancel":
                        self.notes_ui["pending_id"] = None
                    elif a == "note_del":
                        from deskbar.ui import notesview
                        ui = self.notes_ui
                        if (ui["pending_id"] == h.data and
                                time.monotonic() - ui["pending_at"]
                                <= notesview.PENDING_TIMEOUT_S):
                            if self.notes_store is not None:
                                try:
                                    self.notes_store.remove(h.data)
                                except OSError as e:
                                    print(f"[deskbar] note remove failed: {e}",
                                          file=sys.stderr)
                        ui["pending_id"] = None
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
            elif self.view == "bt":
                from deskbar.ui import bt_view
                self.hits = bt_view.render(self.logical, self.bt_ui, self.settings, now)
            elif self.view == "screen":
                from deskbar.ui import screen_view
                self.hits = screen_view.render(self.logical, self.settings)
            elif self.view == "alarms":
                self.hits = alarm_view.render(self.logical, self.alarm_store,
                                              self.alarm_draft, now)
            else:
                self.hits = dashboard.render(self.logical, snap, self.settings, now, clock_anim,
                                             anchor=self.view_anchor,
                                             weather_t=self._weather_t(),
                                             notes_store=self.notes_store,
                                             notes_ui=self.notes_ui,
                                             linear_page=self.center_pages["linear"],
                                             notes_page=self.center_pages["notes"])
                if self.view == "detail" and self.detail_event is not None:
                    self.hits += detail.render(self.logical, self.detail_event)
                elif self.card_overlay is not None:
                    # 待辦卡詳情浮層是 modal：hits 整組換成「點任意處關閉」
                    from deskbar.ui import cardoverlay
                    self.hits = cardoverlay.render(self.logical, self.card_overlay, now)

    def _flip_center_page(self, center: str, delta: int) -> None:
        """待辦/便條牆翻頁：夾在 [0, 總頁數-1]。總頁數依當下資料量現算，
        資料變少時頁碼由 render 端再夾一次（雙保險）。"""
        if center == "linear":
            from deskbar.ui import linearview
            total = linearview.page_count(len(self.state.snapshot().linear))
        else:
            from deskbar.ui import notesview
            total = notesview.page_count(
                len(self.notes_store.list()) if self.notes_store else 0)
        cur = self.center_pages.get(center, 0)
        self.center_pages[center] = max(0, min(total - 1, cur + delta))

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

    def _bt_rescan(self) -> None:
        ui = self.bt_ui
        if ui["busy"]:
            return
        ui["busy"] = "scan"
        import threading
        from deskbar import bt

        def work():
            ui["devices"] = bt.scan()
            ui["busy"] = None

        threading.Thread(target=work, daemon=True, name="bt-scan").start()

    def _bt_pick(self, dev) -> None:
        """未配對→配對＋信任→設為感應目標；已配對→直接切換感應目標。"""
        ui = self.bt_ui
        if ui["busy"]:
            return
        if dev.paired:
            self.settings.presence_mac = dev.mac
            self.on_save(self.settings)
            ui["msg"] = f"感應目標已切換：{dev.name or dev.mac}"
            return
        ui["busy"] = "pair"
        ui["msg"] = ""
        import threading
        from deskbar import bt

        def work():
            ok, msg = bt.pair(dev.mac)
            if ok:
                with self.lock:
                    self.settings.presence_mac = dev.mac
                    self.on_save(self.settings)
                ui["msg"] = f"已配對並設為感應目標：{dev.name or dev.mac}"
                ui["devices"] = bt.scan()
            else:
                ui["msg"] = f"配對失敗：{msg}"
            ui["busy"] = None

        threading.Thread(target=work, daemon=True, name="bt-pair").start()

    def _bt_unpair(self, mac: str) -> None:
        ui = self.bt_ui
        if ui["busy"]:
            return
        ui["busy"] = "unpair"
        import threading
        from deskbar import bt

        def work():
            ok, msg = bt.unpair(mac)
            if ok and self.settings.presence_mac == mac:
                with self.lock:
                    self.settings.presence_mac = ""
                    self.on_save(self.settings)
            ui["msg"] = msg if ok else f"解除失敗：{msg}"
            ui["devices"] = bt.scan()
            ui["busy"] = None

        threading.Thread(target=work, daemon=True, name="bt-unpair").start()

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
        self._flip((0, 0, dashboard.PANEL_W, LOGICAL_H))   # 只有左欄髒

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
        """cycle_span/cycle_view_mode/goto_now/goto_day/翻頁/切中欄 觸發時呼叫：把
        「現在畫面」交給 SlideTransition 存成過場素材。一律限定在中欄內容區滑動
        （CENTER_SLIDE_AREA）——左右欄與頂列 chrome 釘死；目前所有過場來源都是
        中欄內容變化，沒有全頁滑動的正當場景。沒有真的顯示器時（測試直接呼叫
        _dispatch，不經 _init_display）self.logical 不存在，直接跳過。direction>=0：
        舊內容往左滑出／新內容從右側滑入（前進）；direction<0：方向相反（後退）。
        """
        logical = getattr(self, "logical", None)
        if logical is not None:
            import time
            from deskbar.ui.dashboard import CENTER_SLIDE_AREA
            self._transition.start(logical, direction, area=CENTER_SLIDE_AREA)
            self._transition_start = time.monotonic()
            self._transition_cache = None   # 新過場：上一場的「新畫面」快照作廢

    def _render_transition_frame(self, now) -> None:
        """切換過場的其中一幀。「新畫面」只在過場第一幀真正渲染一次、存成快照，
        之後每幀只做快照 blit＋帶狀合成——第一版每幀全量重繪，Pi 上一幀 100ms+，
        0.2s 的動畫實跑 0.6s 還在抖（「卡頓感」元凶之二）。過場僅 0.2s，期間
        時鐘/天氣凍結無感。超過 DURATION 後過場結束、丟快照。"""
        import time
        first = self._transition_cache is None
        if first:
            snap = self.state.snapshot()
            self._draw_frame(snap, now)
            self._transition_cache = (self.logical.copy(), snap.seq, now.minute,
                                      now.strftime("%H:%M"))
        else:
            self.logical.blit(self._transition_cache[0], (0, 0))
        elapsed = time.monotonic() - self._transition_start
        composed = self._transition.frame(self.logical, elapsed)
        if composed is not self.logical:
            self.logical.blit(composed, (0, 0))
        # 首幀＝新畫面上場（chrome 可能整組換），全量；其後只有滑動帶在動
        from deskbar.ui.dashboard import CENTER_SLIDE_AREA as A
        self._flip(None if first else
                   (int(A.x), int(A.y), int(A.w), int(A.h)))
        _frame, self._last_seq, self._last_minute, self._last_clock_text = \
            self._transition_cache
        if not self._transition.active():
            self._transition_start = None
            self._transition_cache = None

    def _handle_touch_up(self, x: int, y: int) -> None:
        """FINGERUP／MOUSEBUTTONUP 共用：判斷是點擊還是時間軸平移拖曳。"""
        if self._pressed_dirty:
            # 按壓高亮畫在 logical 上了，放手後至少重繪一次洗掉
            self._pressed_dirty = False
            self._last_seq = -1
        if self._pan_band is not None:
            # 跟手帶狀位移收工：丟快照、強制全量重繪（由 _pan_view 提交或復原）
            self._pan_band = None
            self._last_seq = -1
        if self.firing:
            # 響鈴中任何觸碰＝全部關掉，不走拖曳判定、不逐顆 pop——
            # (1) 手指滑過 24px 會被當拖曳而不觸發解除；(2) 多顆排隊要一顆
            # 一顆點。兩者在使用者眼裡都是「點了關不掉」（實機深夜回報）。
            self.firing.clear()
            self._drag_start = None
            self._last_seq = -1
            return
        if self.card_overlay is not None:
            # 詳情浮層開著：任何手勢（含滑動）都算「點任意處關閉」，不翻頁
            self._drag_start = None
            self._dispatch(x, y)
            return
        if self._drag_start is None:
            self._dispatch(x, y)
            return
        sx, _sy = self._drag_start
        dx = x - sx
        self._drag_start = None
        from deskbar.ui.dashboard import TL_X0, TL_X1
        center = getattr(self.settings, "center_view", "calendar")
        if center in ("linear", "notes") and self.view == "dashboard":
            # 待辦/便條牆：左右滑動＝翻頁（往左滑看下一頁），點擊照舊 dispatch
            if abs(dx) > DRAG_THRESHOLD and sx > TL_X0:
                before = self.center_pages.get(center, 0)
                direction = +1 if dx < 0 else -1
                self._start_transition(direction)
                self._flip_center_page(center, direction)
                if self.center_pages.get(center, 0) == before:
                    self._transition_start = None   # 已在邊界沒翻成，不播過場
                self._last_seq = -1
            else:
                self._dispatch(x, y)
            return
        if abs(dx) > DRAG_THRESHOLD and sx > TL_X0:
            self._pan_view(dx, TL_X1 - TL_X0)
            self._last_seq = -1      # 放手後強制重繪
        else:
            self._dispatch(x, y)

    def _pan_anchor_from(self, dx_px: float, area_w: float):
        """dx 像素 → 平移後的新錨點（純計算，不落地）。跟手預覽與放手提交共用
        同一套數學——預覽畫面必然等於提交結果，不會放手瞬間跳一下。

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
            return clamp_anchor(new_anchor, now, tz)

    def _pan_view(self, dx_px: float, area_w: float) -> None:
        """時間軸拖曳平移錨點：向右拖＝看過去。範圍 clamp 在資料窗口 [今天-7, 今天+30]。"""
        new_anchor = self._pan_anchor_from(dx_px, area_w)
        with self.lock:
            self.view_anchor = new_anchor

    def _pan_band_preview(self) -> None:
        """拖曳跟手：不重算版面，把「已渲染好的中欄帶」1:1 平移後 flip。

        第一版跟手是拖曳中逐幀全量重繪——Pi Zero 2W 一幀 100ms+，實際 8fps
        橡皮筋感（實機回報「非常不跟手的卡頓感」）。改成拖曳開始時快照中欄
        帶狀畫面，之後每幀只做一次帶狀 blit（幾 ms），內容跟著手指 1:1 移動；
        滑出範圍的邊緣先留底色，放手時 _pan_view 提交錨點、全量重繪補上。
        只在 dashboard 行事曆中欄生效。"""
        if (self.view != "dashboard" or self._drag_start is None
                or self._drag_last is None or self._transition_start is not None
                or self.firing or self.card_overlay is not None):
            return
        if getattr(self.settings, "center_view", "calendar") != "calendar":
            return
        from deskbar.ui.dashboard import CENTER_SLIDE_AREA, TL_X0
        sx, _sy = self._drag_start
        lx, _ly = self._drag_last
        if sx <= TL_X0 or abs(lx - sx) <= DRAG_THRESHOLD:
            return
        mono = time.monotonic()
        if mono - self._pan_band_at < PAN_BAND_INTERVAL:
            return
        self._pan_band_at = mono
        r = pygame.Rect(int(CENTER_SLIDE_AREA.x), int(CENTER_SLIDE_AREA.y),
                        int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h))
        if self._pan_band is None:
            self._pan_band = self.logical.subsurface(r).copy()
        dx = max(-r.w, min(r.w, int(lx - sx)))
        prev_clip = self.logical.get_clip()
        self.logical.set_clip(r)
        self.logical.fill(theme.C["bg"], r)
        self.logical.blit(self._pan_band, (r.x + dx, r.y))
        self.logical.set_clip(prev_clip)
        self._flip(r)

    def _press_feedback(self, x: int, y: int) -> None:
        """按下瞬間的視覺回饋（目標 <50ms）：命中可點元素就疊一層高亮並立即
        flip。體感延遲的關鍵不是總延遲，是按下當下畫面有沒有立刻回應——
        50ms 內給高亮，即使後續重繪要 200ms，大腦也判定「有反應」。"""
        if self.firing or getattr(self, "logical", None) is None:
            return
        for h in reversed(self.hits):
            if h.rect.contains(x, y) and h.action != "noop":
                r = pygame.Rect(int(h.rect.x), int(h.rect.y),
                                max(1, int(h.rect.w)), max(1, int(h.rect.h)))
                glow = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                color = ((0, 0, 0, 34) if theme.current_theme() == "light"
                         else (255, 255, 255, 34))
                pygame.draw.rect(glow, color, glow.get_rect(), border_radius=10)
                self.logical.blit(glow, r.topleft)
                self._pressed_dirty = True
                self._flip(r)
                return

    def _screen_asleep(self) -> bool:
        """深夜熄屏中（睡眠時段內且沒有觸摸喚醒）＝畫面全黑。
        響鈴中一律視為醒著——鬧鐘在全黑幕底下閃等於沒響，且解除的那一觸
        不該被當成喚醒觸吞掉。"""
        if self.firing:
            return False
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from deskbar import brightness
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        return brightness.effective(
            self.settings, now.hour * 60 + now.minute,
            awake=time.monotonic() < self._wake_until) == 0

    def _auto_center_tick(self, snap, now) -> None:
        """迫近行程搶焦點：AUTO_SWITCH_BEFORE_MIN 分鐘內要開始的行程 → 中欄自動
        切回行事曆（會看到迫近脈動卡）；行程開始 5 分鐘後或沒有迫近行程了，切回
        使用者原本的視圖。使用者中途手動切換（toggle_center）即接管、本輪取消。
        這是「智慧儀表板」跟「三個切著看的 app」的分水嶺。"""
        if self.view != "dashboard" or self._transition_start is not None:
            return
        soon = False
        for e in snap.events:
            if e.all_day:
                continue
            lead_min = (e.start - now).total_seconds() / 60
            if -5 <= lead_min <= AUTO_SWITCH_BEFORE_MIN:
                soon = True
                break
        with self.lock:
            cur = getattr(self.settings, "center_view", "calendar")
            if not soon:
                self._auto_center_hold = False   # 這一波過了，下一波恢復搶焦點
            if soon and not self._auto_center_hold \
                    and cur != "calendar" and self._auto_center_prev is None:
                self._auto_center_prev = cur
                self.settings.center_view = "calendar"   # 記憶體內切換，不持久化
                switched = True
            elif not soon and self._auto_center_prev is not None:
                if cur == "calendar":
                    self.settings.center_view = self._auto_center_prev
                self._auto_center_prev = None
                switched = True
            else:
                switched = False
        if switched:
            self._start_transition()
            self._last_seq = -1

    def _service_screenshot(self) -> None:
        """配合 /api/screenshot：把目前邏輯畫面（未疊亮度黑幕的原畫面）編成
        PNG 丟回橋。pygame Surface 不是執行緒安全，只能由 render 執行緒做，
        webserver 端設 want 旗標後等 done。"""
        import io
        b = self.shot_bridge
        try:
            buf = io.BytesIO()
            pygame.image.save(self.logical, buf, "shot.png")
            b["data"] = buf.getvalue()
        except Exception:
            b["data"] = None
        b["want"].clear()
        b["done"].set()

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

    def _touch_down(self, x: int, y: int) -> None:
        """FINGERDOWN／MOUSEBUTTONDOWN 共用：熄屏中第一觸＝喚醒（吞掉不當操作）；
        平常＝記下拖曳起點＋立即畫按壓高亮。"""
        if self._screen_asleep():
            self._wake_until = time.monotonic() + WAKE_SECONDS
            self._swallow_touch = True
            self._drag_start = None
            self._last_seq = -1     # 立刻重繪＝亮回來
            return
        self._drag_start = (x, y)
        self._drag_last = (x, y)
        self._press_feedback(x, y)

    def _run_iteration(self, clock, running: bool) -> bool:
        had_input = False        # 這一圈有無輸入事件：有＝後續節拍全部提速
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_r:
                had_input = True
                self._cycle_dev_rotate()
            elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False
            elif ev.type == pygame.FINGERDOWN:
                had_input = True
                x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                self._touch_down(x, y)
            elif ev.type == pygame.FINGERMOTION:
                had_input = True
                if self._drag_start is not None:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self._drag_last = (x, y)
            elif ev.type == pygame.FINGERUP:
                had_input = True
                if self._swallow_touch:
                    self._swallow_touch = False
                else:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self._handle_touch_up(x, y)
            elif ev.type == pygame.MOUSEBUTTONDOWN:   # dev 模式滑鼠模擬觸控
                had_input = True
                x, y = transform.dev_window_to_logical(
                    ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                self._touch_down(x, y)
            elif ev.type == pygame.MOUSEMOTION:
                if self._drag_start is not None:
                    had_input = True
                    x, y = transform.dev_window_to_logical(
                        ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                    self._drag_last = (x, y)
            elif ev.type == pygame.MOUSEBUTTONUP:
                had_input = True
                if self._swallow_touch:
                    self._swallow_touch = False
                else:
                    x, y = transform.dev_window_to_logical(
                        ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                    self._handle_touch_up(x, y)
        if self._drag_start is not None:
            # 跟手位移每圈只做一次（motion 事件常一圈湧進 3-5 顆，逐顆 flip 白燒）
            self._pan_band_preview()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        mono = time.monotonic()
        if self.shot_bridge is not None and self.shot_bridge["want"].is_set():
            self._service_screenshot()
        if self._wake_until and mono >= self._wake_until:
            self._wake_until = 0.0
            self._last_seq = -1     # 喚醒到期，重繪一次回到黑幕
        if mono - self._auto_center_check_at >= 5.0:
            self._auto_center_check_at = mono
            self._auto_center_tick(self.state.snapshot(), now)
        if self.alarm_store is not None:
            due = self.alarm_store.due(self._last_alarm_check, now)
            self._last_alarm_check = now
            if due:
                self.firing.extend(due)
                self._firing_since = mono   # 新來的鬧鐘重置計時：每顆都有完整 5 分鐘
                self._last_seq = -1
        if self.firing:
            if mono - self._firing_since > ALARM_AUTO_DISMISS_S:
                # 響 5 分鐘沒人理＝人不在，自動解除（實機需求：不然閃一整晚，
                # 深夜還會一直以「響鈴=醒著」壓過熄屏）
                self.firing.clear()
                self._last_seq = -1
            else:
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
            if self._screen_asleep():
                # 深夜熄屏：不燒氛圍幀、輪詢降到 2fps（整夜 15fps 畫給黑幕看
                # 純屬浪費）；觸摸喚醒那一圈 had_input=True 立即提速。
                if snap.seq != self._last_seq or now.minute != self._last_minute:
                    self._render()
                clock.tick(30 if had_input else 2)
            elif (self.view == "dashboard"
                    and getattr(self.settings, "center_view", "") == "notes"
                    and self.notes_ui.get("pending_id")):
                # 便條「再點一下撕掉」的 5 秒逾時回復需要重繪才看得到
                self._render()
                clock.tick(10 if had_input else 2)
            elif self.view in ("wifi", "bt"):
                # Wi-Fi／藍牙頁：掃描/連線/配對結束由背景執行緒改 ui dict，沒有
                # seq 可觸發，靠輪詢重繪跟上。閒置 5fps；打字中提速到 20fps——
                # 鍵盤 200ms 一格的回饋就是「十年前」體感的元凶之一。
                self._render()
                clock.tick(20 if had_input else 5)
            elif snap.seq != self._last_seq or now.minute != self._last_minute:
                self._render()
                clock.tick(30)
            elif self._ambient_active(snap) and not had_input:
                # 資料/分鐘都沒變，但天氣場景要動：左欄局部重繪，幀率按場景分級。
                # 歷史教訓（2026-07-27「根本看不到動畫」）：這裡以前只有上面那條
                # 全量重繪，天氣 tick 每秒都在加、畫面卻一分鐘才畫一次。
                # had_input 時讓路給輸入處理（例如跟手預覽剛全量重繪過）。
                self._render_ambient(snap, now)
                from deskbar.ui import weatherfx
                clock.tick(weatherfx.ambient_fps(snap.weather.code))
            else:
                # 純閒置輪詢從 10fps 提到 30fps：一次觸控最慢 100ms 後才被看見，
                # 是延遲感的最大單一來源。空圈只做事件泵＋幾個判斷，30fps 的
                # CPU 成本 <3%，換來輸入延遲上限 33ms。
                clock.tick(30)
        return running
