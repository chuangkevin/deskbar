import os
import sys
import time
import traceback

import pygame

from deskbar import transform
from deskbar.layout import Rect
from deskbar.ui import Hit
from deskbar.ui import theme
from deskbar.ui.navigation import NavigationState
from deskbar.ui.pet_overlay import PetOverlayController
from deskbar.ui.scene_mode import SceneModeController

LOGICAL_W, LOGICAL_H = 1920, 480
DRAG_THRESHOLD = 24                     # px，觸控拖曳判定門檻
SYNC_INTERVALS = [1, 3, 5, 10, 30]       # 設定頁「同步頻率」鈕的循環清單（分鐘）
WAKE_SECONDS = 30                        # 深夜熄屏中觸摸喚醒的持續秒數
ALARM_AUTO_DISMISS_S = 300               # 響鈴 5 分鐘沒人理＝自動解除（不然閃一整晚）
AUTO_SWITCH_BEFORE_MIN = 15              # 迫近行程搶焦點：開始前 N 分鐘自動切回行事曆
FORCE_SCENE_RETURN_S = 60                # force 場景模式：點回行事曆後 N 秒自動回場景
PAN_BAND_INTERVAL = 1 / 30               # 跟手位移的 flip 節流（帶狀 blit 很便宜，30fps 上限即可）
# 2026-08-10 Pi Zero 2W 實測頁面拖曳單圈工作只要 13.7ms，卻被 tick(30) 睡到
# 33.2ms；拖曳／吸附改為 60fps，才能避免手指跟隨被多餘的約 20ms 睡眠拖慢。
DRAG_FPS = 60
PAN_BAND_INTERVAL_DRAG = 1 / 60          # 頁面拖曳帶狀 blit 要配合 60fps 跟手
# 氛圍幀率不是常數：由 weatherfx.ambient_fps(code) 分級（雨/雷 15、雪 12、
# 晴/雲/霧 8）——實務上 open-meteo 的每個 code 都有動態場景，氛圍模式是 24/7
# 常態，分級幀率才是 Pi Zero 2W 上真正的省電槓桿。

PAGE_FLIP_RATIO = 0.25      # 拖過帶寬的 1/4 就翻頁
PAGE_EDGE_RESIST = 3        # 邊界外拖的阻尼倍率
PAGE_SETTLE_S = 0.15        # 放手吸附動畫時長（秒）
PREFETCH_IDLE_S = 2.0       # 相鄰頁預取前必須連續閒置的秒數


def should_prefetch(idle_since: float, now_mono: float, threshold: float) -> bool:
    return idle_since != 0.0 and now_mono - idle_since >= threshold


def loop_fps(drag_active: bool, default_fps: int = 30) -> int:
    """拖曳／吸附進行中回 DRAG_FPS，其餘回 default_fps。"""
    return DRAG_FPS if drag_active else default_fps


def page_drag_offset(dx: float, width: int, has_prev: bool, has_next: bool) -> float:
    """拖曳中內容實際要位移多少 px。
    往左拖（dx<0）＝要看下一頁：沒有下一頁時只給 dx/PAGE_EDGE_RESIST 的阻尼
    位移（橡皮筋手感，讓使用者知道到底了），有下一頁就 1:1。
    往右拖同理對應上一頁。位移量一律夾在 [-width, width]。
    """
    if dx < 0:
        raw = dx if has_next else dx / PAGE_EDGE_RESIST
    elif dx > 0:
        raw = dx if has_prev else dx / PAGE_EDGE_RESIST
    else:
        raw = 0.0
    w = float(width)
    return max(-w, min(w, float(raw)))


def page_drag_decision(dx: float, width: int, has_prev: bool, has_next: bool) -> int:
    """放手時回 +1（翻到下一頁）／-1（上一頁）／0（彈回原頁）。
    |dx| 必須超過 width * PAGE_FLIP_RATIO 才算數；方向上沒有頁可翻時一律回 0。
    dx<0 → +1（往左滑看下一頁），dx>0 → -1。
    """
    threshold = width * PAGE_FLIP_RATIO
    if abs(dx) <= threshold or dx == 0:
        return 0
    if dx < 0:
        return 1 if has_next else 0
    else:
        return -1 if has_prev else 0


def rot_offset(dx: float, angle: int) -> tuple[float, float]:
    """把 logical 水平位移換成 pygame.rotate(angle) 後的輸出面位移。

    這段複雜度只是為了 Pi Zero 2W：實機量到拖曳帶狀區域每幀旋轉要 18.3ms，
    會把拖曳壓到 22fps。若改用 Pi 4 這類旋轉只要 3-5ms 的板子，可以刪掉
    這條預旋轉捷徑，回到單純畫 logical 再 _flip(rect) 的寫法。
    """
    a = angle % 360
    if a == 0:
        return (dx, 0.0)
    if a == 180:
        return (-dx, 0.0)
    if a == 270:   # angle == -90；pygame.rotate(-90) 是順時針。
        # 推導：_map_rot 對 -90 回 (lh - y - h, x)，同一矩形水平移 dx 後，
        # 旋轉輸出面的 x 不變、y 變成 x + dx，所以往左拖(dx<0)會往上。
        return (0.0, dx)
    if a == 90:
        # 與 -90 相反：_map_rot 對 +90 回 (y, lw - x - w)，水平移 dx 後 y 減 dx。
        return (0.0, -dx)
    return (dx, 0.0)



class App:
    def __init__(self, state, settings, settings_lock, on_save, alarm_store=None,
                 notes_store=None, shot_bridge=None):
        self.state = state
        self.settings = settings
        self.lock = settings_lock
        self.on_save = on_save          # callable：settings 變更後持久化
        self.nav = NavigationState(view="dashboard")
        self.scene_controller = SceneModeController()
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
        self._last_imminent_check = None  # 迫近行程：上次檢查時間（每秒檢查一次即可）
        self._imminent_active = False     # 迫近行程：本秒是否有迫近中的行程
        self._weather_epoch = time.monotonic()   # 天氣場景時間基準：t＝距開機浮點秒數
        from deskbar.ui import bt_view, wifi_view
        self.wifi_ui = wifi_view.new_state()     # Wi-Fi 設定頁狀態（背景執行緒共寫）
        self.bt_ui = bt_view.new_state()         # 藍牙配對頁狀態（背景執行緒共寫）
        self._veil = None                        # 亮度疊黑快取：(size, alpha, surface)
        # 待辦/便條牆目前頁碼由 NavigationState 管；App.center_pages 保留相容 property。
        self.shot_bridge = shot_bridge  # /api/screenshot 的跨執行緒橋（want/done/data）
        self._pressed_dirty = False     # 按壓高亮畫上去了，放手後要洗掉
        self._wake_until = 0.0          # 熄屏觸摸喚醒的截止時刻（monotonic）
        self._swallow_touch = False     # 熄屏中的第一觸＝喚醒，不當作操作
        self._pan_band = None           # 跟手拖曳：中欄帶狀快照（拖曳中 1:1 位移，放手清除）
        self._pan_band_at = 0.0
        self._page_drag = None          # 待辦/便條牆跟手拖曳：中欄帶狀快照狀態
        self._page_drag_at = 0.0
        self._page_settle = None        # 待辦/便條牆放手吸附動畫狀態
        self._band_cache = {}           # (中欄視圖, 頁碼) → 閒置時預畫的帶狀 Surface
        self._band_cache_key = None     # (中欄視圖, snap.seq, 該視圖資料筆數)
        self._idle_since = 0.0          # 相鄰頁預取的連續閒置起點（monotonic）
        self._dev = False
        self._dev_rotate = 0
        self._rot_cache = None          # 實機旋轉輸出快取：髒區域局部旋轉的基底
        self._rot_angle = None
        self._auto_center_check_at = 0.0
        self.card_overlay = None        # 待辦卡詳情浮層（LinearIssue|None）
        self.work_sessions_page = 0     # 全螢幕工作 Session 清單頁碼
        from deskbar.presence import SedentaryTracker
        self.sedentary = SedentaryTracker()   # 久坐提示（公司場景：連續在座 60 分）
        self._sed_hint_last = False           # 提示出現/消失的邊緣觸發重繪用
        from deskbar.claudeusage import UsageActivity
        from deskbar.ui import scenes
        self.usage_activity = UsageActivity()  # 忙/閒判定（usage 增量＝在寫 code）
        self.scene_ui = scenes.new_state()     # 氛圍場景跨幀狀態（軌跡面/粒子）
        self.pet_overlay = PetOverlayController(settings)  # 小喜喜：全域桌面寵物 overlay
        self.pet_ui = self.pet_overlay.pet      # 相容既有診斷／測試的 sprite access
        self._flow_check_at = 0.0
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        self.alarm_draft = {"hour": (now.hour + 1) % 24, "minute": 0, "days": set(),
                             "label_idx": 0}

    @property
    def view(self) -> str:
        return self.nav.view

    @view.setter
    def view(self, value: str) -> None:
        try:
            self.nav.set_view(value)
        except ValueError:
            # Backward compatibility: old tests and diagnostics could assign a
            # sentinel string directly to app.view. NavigationState.set_view()
            # remains strict for production route changes.
            self.nav.view = value

    @property
    def center_pages(self) -> dict[str, int]:
        return self.nav.center_pages

    @center_pages.setter
    def center_pages(self, value: dict[str, int]) -> None:
        self.nav.center_pages = {
            "linear": max(0, int(value.get("linear", 0))),
            "notes": max(0, int(value.get("notes", 0))),
        }

    @property
    def _transition(self):
        return self.nav.transition

    @_transition.setter
    def _transition(self, value) -> None:
        self.nav.transition = value

    @property
    def _transition_start(self):
        return self.nav.transition_start

    @_transition_start.setter
    def _transition_start(self, value) -> None:
        self.nav.transition_start = value

    @property
    def _transition_cache(self):
        return self.nav.transition_cache

    @_transition_cache.setter
    def _transition_cache(self, value) -> None:
        self.nav.transition_cache = value

    @property
    def _auto_center_prev(self):
        return self.scene_controller.auto_center_prev

    @_auto_center_prev.setter
    def _auto_center_prev(self, value) -> None:
        self.scene_controller.auto_center_prev = value

    @property
    def _auto_center_hold(self) -> bool:
        return self.scene_controller.auto_center_hold

    @_auto_center_hold.setter
    def _auto_center_hold(self, value: bool) -> None:
        self.scene_controller.auto_center_hold = bool(value)

    @property
    def _flow_last_target(self):
        return self.scene_controller.flow_last_target

    @_flow_last_target.setter
    def _flow_last_target(self, value) -> None:
        self.scene_controller.flow_last_target = value

    @property
    def _force_scene_at(self) -> float:
        return self.scene_controller.force_scene_at

    @_force_scene_at.setter
    def _force_scene_at(self, value: float) -> None:
        self.scene_controller.force_scene_at = float(value)

    @property
    def _pet_dragging(self) -> bool:
        """相容既有診斷；實際的 pointer capture 由 PetOverlayController 持有。"""
        return self.pet_overlay.dragging

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

    def _page_drag_rot_fields(self, cur, neighbour, r: "pygame.Rect") -> dict:
        """建立待辦/便條牆拖曳用的預旋轉快照欄位。

        這是 Pi Zero 2W 的慢硬體妥協：拖曳時內容只是在平移，若每幀把同一張
        1118x428 快照旋轉一次會白燒 18.3ms；起手先轉好，後續只 blit。
        _dev 路徑保留原本 logical→_flip 的簡單管線，方便開發機觀察。
        """
        if self._dev or cur is None:
            return {}
        angle = transform.pygame_rotation_angle(self.settings.rotation)
        return {
            "cur_rot": pygame.transform.rotate(cur, angle),
            "neighbour_rot": pygame.transform.rotate(neighbour, angle)
            if neighbour is not None else None,
            "angle": angle,
            "rot_base": self._map_rot(r, angle),
        }

    def _flip(self, dirty=None, apply_veil: bool = True) -> None:
        """dirty（logical 座標的 Rect|tuple|None）：這一幀只有該區域變了。
        實機路徑據此只旋轉髒區域、貼回持久的旋轉快取——整張 1920×480 旋轉
        （92 萬像素）是每幀固定稅，氛圍幀只動左欄(400 寬)、拖曳只動中欄，
        局部旋轉把這筆稅砍到 1/5～1/2（實機 70% CPU 的主成分）。
        亮度疊黑改蓋在 screen 上，旋轉快取永遠保持乾淨原圖。

        局部更新時整片重疊 veil 是每幀固定稅，實機量到 17.9ms，
        佔 45.4ms 的四成，是拖曳掉到 22fps 的主因（2026-08-06 實機量測）。
        """
        if self._dev:
            # dev：外層旋轉直接作用在邏輯畫面上（0=轉正全景），不經實機面板管線
            out = self.logical if self._dev_rotate == 0 \
                else pygame.transform.rotate(self.logical, -self._dev_rotate)
            out = pygame.transform.smoothscale(out, self.win)
            veil = self._dim_veil(out.get_size()) if apply_veil else None
            if veil is not None:
                out.blit(veil, (0, 0))
            if getattr(self, "screen", None) is not None:
                self.screen.blit(out, (0, 0))
        else:
            angle = transform.pygame_rotation_angle(self.settings.rotation)
            dst_rect = None
            if self._rot_cache is None or self._rot_angle != angle or dirty is None:
                self._rot_cache = pygame.transform.rotate(self.logical, angle)
                self._rot_angle = angle
            else:
                r = pygame.Rect(dirty).clip(self.logical.get_rect())
                if r.w > 0 and r.h > 0:
                    sub = pygame.transform.rotate(self.logical.subsurface(r), angle)
                    rot_pos = self._map_rot(r, angle)
                    self._rot_cache.blit(sub, rot_pos)
                    screen_rect = self.screen.get_rect() if getattr(self, "screen", None) is not None \
                        else pygame.Rect(0, 0, self._rot_cache.get_width(), self._rot_cache.get_height())
                    dst_rect = pygame.Rect(rot_pos, sub.get_size()).clip(screen_rect)
                else:
                    dst_rect = pygame.Rect(0, 0, 0, 0)
            if getattr(self, "screen", None) is not None:
                veil = self._dim_veil(self._rot_cache.get_size()) if apply_veil else None
                if dst_rect is None:
                    # 全量更新：整片 blit rot_cache 與 veil
                    self.screen.blit(self._rot_cache, (0, 0))
                    if veil is not None:
                        self.screen.blit(veil, (0, 0))
                elif dst_rect.w > 0 and dst_rect.h > 0:
                    # 局部更新：局部重疊 veil 是每幀固定稅 (17.9ms/45.4ms，2026-08-06 實機量測)
                    # rot_cache 與 veil 都只 blit 旋轉後的髒區域 (dst_rect)
                    self.screen.blit(self._rot_cache, dst_rect.topleft, dst_rect)
                    if veil is not None:
                        self.screen.blit(veil, dst_rect.topleft, dst_rect)
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
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
                    from deskbar.ui.settings_flow import decide_settings_flow
                    flow = decide_settings_flow(a)
                    if flow is not None:
                        self.view = flow.view
                        if flow.clear_wifi_message:
                            self.wifi_ui["msg"] = ""
                        if flow.rescan_wifi:
                            self._wifi_rescan()
                        if flow.rescan_bt:
                            self._bt_rescan()
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
                    elif a == "bt_rescan":
                        self._bt_rescan()
                    elif a == "bt_pick":
                        self._bt_pick(h.data)
                    elif a == "bt_unpair":
                        self._bt_unpair(h.data)
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
                                                selected_profile_id=net.profile_id,
                                                selected_secured=True,
                                                selected_security=net.security,
                                                pw="", msg="",
                                                shift=False, sym=False, show_pw=False)
                        else:
                            self._wifi_connect(net.ssid, None, net.security, net.profile_id)
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
                                               self.wifi_ui.get("selected_security", ""),
                                               self.wifi_ui.get("selected_profile_id", ""))
                    elif a == "open_detail":
                        self.view, self.detail_event = "detail", h.data
                    elif a == "open_work_sessions":
                        self._start_transition()
                        if self.view != "dashboard":
                            self.view = "dashboard"
                        self.settings.center_view = "sessions"
                        self.state.mark_work_sessions_seen()
                        self.on_save(self.settings)
                    elif a == "go_dashboard":
                        self.view = "dashboard"
                    elif a == "work_sessions_page":
                        self.work_sessions_page = max(0, int(h.data))
                    elif a == "enqueue_work_session_action":
                        # h.data 是 Mac 產生的 opaque capability。AppState 會再次
                        # 驗證它仍屬於 30 分鐘內顯示中的 item，絕不接收 command。
                        self.state.enqueue_work_session_action(str(h.data))
                    elif a == "toggle_alarm":
                        if self.alarm_store is not None:
                            try:
                                self.alarm_store.toggle(h.data)
                            except OSError as e:
                                print(f"[deskbar] alarm toggle write failed: {e}",
                                      file=sys.stderr)
                    elif a == "skip_alarm":
                        if self.alarm_store is not None:
                            try:
                                from datetime import datetime
                                from zoneinfo import ZoneInfo
                                today_s = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
                                target = next((x for x in self.alarm_store.list() if x.id == h.data), None)
                                if target is not None:
                                    if target.skip_date == today_s:
                                        self.alarm_store.set_skip_date(h.data, None)
                                    else:
                                        self.alarm_store.set_skip_date(h.data, today_s)
                            except OSError as e:
                                print(f"[deskbar] alarm skip write failed: {e}",
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
                        cur = getattr(self.settings, "center_view", "calendar")
                        switch = self.scene_controller.manual_cycle(cur)
                        self.settings.center_view = switch.center_view
                        if switch.center_view == "sessions":
                            self.state.mark_work_sessions_seen()
                        if switch.reset_center_pages:
                            self.nav.reset_center_pages()
                        # 使用者手動切換＝接管：取消還原、且這一波迫近期間不再搶焦點
                        # （沒 hold 的話 5 秒後又被抓回行事曆——本機測試實測踩到）
                        if switch.clear_card_overlay:
                            self.card_overlay = None
                        if switch.persist:
                            self.on_save(self.settings)
                    elif a == "scene_tap":
                        # 點場景＝回行事曆看正事；force 模式 60 秒後自動回場景。
                        # 這整個 dispatch 鏈已在外層 with self.lock: 內（203 行），
                        # 不得再取鎖（非重入鎖，會死結——測試卡死抓到的）。
                        self._start_transition()
                        switch = self.scene_controller.scene_tap(
                            getattr(self.settings, "scene_mode", "auto"),
                            time.monotonic(),
                            FORCE_SCENE_RETURN_S,
                        )
                        self.settings.center_view = switch.center_view
                        self._last_seq = -1
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

    @staticmethod
    def _union_dirty(*rects) -> "pygame.Rect | None":
        out = None
        for rect in rects:
            if rect is None:
                continue
            r = pygame.Rect(rect).clip(pygame.Rect(0, 0, LOGICAL_W, LOGICAL_H))
            if r.w <= 0 or r.h <= 0:
                continue
            out = r if out is None else out.union(r)
        return out

    def _pet_visible(self) -> bool:
        return bool(getattr(self.settings, "pet_enabled", True)) \
            and not self.firing and not self._screen_asleep()

    def _sleep_pet_visible(self) -> bool:
        return bool(getattr(self.settings, "pet_enabled", True)) \
            and not self.firing and self._screen_asleep()

    def _render_pet_tick(self, now, force: bool = False) -> bool:
        mono = time.monotonic()
        dirty = self.pet_overlay.advance_draw(
            getattr(self, "logical", None), mono=mono,
            visible=self._pet_visible(), force=force,
        )
        if dirty is not None:
            self._flip(dirty)
            return True
        return False

    def _render_sleep_frame(self, now) -> None:
        """深夜全黑時只畫一張黑底＋睡著的小喜喜。

        不能走一般亮度 veil：veil alpha=255 會把寵物一起蓋掉。這裡直接把
        logical 變成黑畫布，再把睡姿 sprite 疊上去，最後用 apply_veil=False
        輸出；因此實機畫面與 /api/screenshot 都看得到睡著的小喜喜。
        """
        self.logical.fill((0, 0, 0))
        self.hits = []
        self.pet_overlay.draw_sleep(
            self.logical, mono=time.monotonic(), visible=self._sleep_pet_visible())
        self._flip(apply_veil=False)

    def _draw_frame(self, snap, now, clock_anim=None, include_pet: bool = True) -> None:
        """把目前 view 畫進 self.logical（不 flip、不動 _last_* 記帳）。
        拆出這支給 _render()（正常重繪）與 _render_transition_frame()（切換過場，
        還要在這之上疊一層舊畫面滑出效果）共用。"""
        from deskbar.ui import alarm_view, dashboard, detail, settings_view, worksessionwidget
        self.logical.fill(theme.C["bg"])
        self.pet_overlay.clear_background()
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
            elif self.view == "work_sessions":
                self.hits = worksessionwidget.render_full_view(
                    self.logical, snap, now, page=self.work_sessions_page)
            else:
                self.hits = dashboard.render(self.logical, snap, self.settings, now, clock_anim,
                                             anchor=self.view_anchor,
                                             weather_t=self._weather_t(),
                                             notes_store=self.notes_store,
                                             notes_ui=self.notes_ui,
                                             linear_page=self.nav.center_page("linear"),
                                             notes_page=self.nav.center_page("notes"),
                                             sedentary=self.sedentary.hint_active(
                                                 time.monotonic()))
                if self.view == "detail" and self.detail_event is not None:
                    self.hits += detail.render(self.logical, self.detail_event)
                elif self.card_overlay is not None:
                    # 待辦卡詳情浮層是 modal：hits 整組換成「點任意處關閉」
                    from deskbar.ui import cardoverlay
                    self.hits = cardoverlay.render(self.logical, self.card_overlay, now)
        if include_pet:
            self.pet_overlay.draw(self.logical, visible=self._pet_visible())

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
        self.nav.flip_center_page(center, delta, total)

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

    def _wifi_connect(self, ssid: str, password: "str | None" = None,
                      security: str = "", profile_id: str = "") -> None:
        """背景連線（nmcli 最長 60 秒）。成功→清密碼、回列表、重掃；
        失敗→留在原畫面顯示原因讓使用者改密碼重試。"""
        ui = self.wifi_ui
        if ui["busy"]:
            return
        ui["busy"] = "connect"
        ui["selected"] = ssid
        ui["selected_profile_id"] = profile_id
        ui["selected_security"] = security
        ui["msg"] = ""
        import threading
        from deskbar import wifi

        def work():
            ok, msg = wifi.connect(ssid, password, security, profile_id)
            if ok:
                ui.update(phase="list", pw="", msg=f"已連線 {ssid}")
                ui["nets"] = wifi.scan()
                ui["active"] = wifi.active_info()
            elif password is None and profile_id and security not in ("", "--"):
                # 已存 secure profile 無密碼 start 失敗時進入原有 password 畫面
                ui.update(phase="password", selected=ssid,
                          selected_profile_id=profile_id,
                          selected_secured=True,
                          selected_security=security,
                          pw="", shift=False, sym=False, show_pw=False,
                          msg="已儲存連線失敗，請輸入密碼重試；原設定會保留")
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

    def _scene_active(self) -> bool:
        """中欄正在跑氛圍場景（需要中欄也吃氛圍幀）。過場中不算——過場自己
        全量重繪。"""
        return (self.view == "dashboard" and not self.nav.transition_active()
                and getattr(self.settings, "center_view", "") == "scene")

    def _check_flow_center(self, mono: float) -> None:
        """忙/閒中欄自動排程（決策在 claudeusage.flow_target）：
        - 只在 dashboard、螢幕醒著、無迫近接管時動作
        - edge-trigger：只在目標「變化」那一刻切一次；同一狀態內使用者手動
          切到哪就停在哪（不會被反覆搶回）
        - 記憶體內切換不持久化，跟迫近搶焦點同一套約定"""
        from deskbar.claudeusage import flow_target
        has_notes = bool(self.notes_store.list()) if self.notes_store else False
        target = flow_target(self.usage_activity.scene_ready(mono),
                             self.usage_activity.busy(mono), has_notes)
        with self.lock:
            switch = self.scene_controller.flow_switch(
                current_center=getattr(self.settings, "center_view", "calendar"),
                target=target,
                view=self.view,
                screen_asleep=self._screen_asleep(),
            )
            if switch is None:
                return
            self.settings.center_view = switch.center_view
            if switch.reset_center_pages:
                self.nav.reset_center_pages()
        self._start_transition()
        self._last_seq = -1

    def _check_force_scene(self, mono: float) -> None:
        """force 模式：中欄常駐場景。點畫面回行事曆（scene_tap 設了返回時刻），
        時間到自動回到場景；迫近接管期間讓路。"""
        with self.lock:
            switch = self.scene_controller.force_switch(
                current_center=getattr(self.settings, "center_view", "calendar"),
                view=self.view,
                screen_asleep=self._screen_asleep(),
                mono=mono,
            )
            if switch is None:
                return
            self.settings.center_view = switch.center_view
        self._start_transition()
        self._last_seq = -1

    def _render_ambient(self, snap, now) -> None:
        """氛圍幀：資料/分鐘都沒變時，只重畫左欄（時鐘/天氣場景）再合成輸出，
        不重算中欄行事曆與右欄油表——Pi Zero 2W 燒不起整面 15fps 全量重繪。
        不動 hits、不動 _last_* 記帳：這一幀對「什麼時候需要全量重繪」的判斷
        完全透明。"""
        old_pet = self.pet_overlay.restore(self.logical)
        with self.lock:
            from deskbar.ui import dashboard
            dashboard.render_panel_only(self.logical, snap, self.settings, now,
                                        self._weather_t(),
                                        sedentary=self.sedentary.hint_active(
                                            time.monotonic()))
            dirty = (0, 0, dashboard.PANEL_W, LOGICAL_H)   # 預設只有左欄髒
            if self._scene_active():
                # 場景幀：中欄也要動——流場粒子畫進 logical，日光帶跟著補回
                # （場景 fill 會蓋掉中欄段的帶），髒區擴到中欄右緣
                from deskbar.ui import scenes, sunstrip
                scenes.render(self.logical, self.scene_ui, now, self._weather_t(),
                              enabled=getattr(self.settings, "scenes_enabled",
                                              None),
                              weather_code=snap.weather.code
                              if snap.weather else None)
                w = snap.weather
                sunstrip.draw(self.logical, now, self.settings.weather_lat,
                              self.settings.weather_lon,
                              rise=getattr(w, "sunrise", None) if w else None,
                              sset=getattr(w, "sunset", None) if w else None)
                dirty = (0, 0, dashboard.TL_X1, LOGICAL_H)
        mono = time.monotonic()
        self.pet_overlay.advance_if_due(mono)
        new_pet = self.pet_overlay.draw(self.logical, visible=self._pet_visible())
        self._flip(self._union_dirty(dirty, old_pet, new_pet) or dirty)

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
        if self._screen_asleep():
            self._render_sleep_frame(now)
            self._last_seq = snap.seq
            self._last_minute = now.minute
            self._last_clock_text = now.strftime("%H:%M")
            return
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
            from deskbar.ui.dashboard import CENTER_SLIDE_AREA
            self.pet_overlay.restore(logical)
            self.nav.start_transition(
                logical, direction, CENTER_SLIDE_AREA, time.monotonic())

    def _render_transition_frame(self, now) -> None:
        """切換過場的其中一幀。「新畫面」只在過場第一幀真正渲染一次、存成快照，
        之後每幀只做快照 blit＋帶狀合成——第一版每幀全量重繪，Pi 上一幀 100ms+，
        0.2s 的動畫實跑 0.6s 還在抖（「卡頓感」元凶之二）。過場僅 0.2s，期間
        時鐘/天氣凍結無感。超過 DURATION 後過場結束、丟快照。"""
        import time
        first = self.nav.transition_cache is None
        if first:
            snap = self.state.snapshot()
            self._draw_frame(snap, now, include_pet=False)
            self.nav.transition_cache = (
                self.logical.copy(), snap.seq, now.minute, now.strftime("%H:%M"))
        else:
            self.pet_overlay.clear_background()
            self.logical.blit(self.nav.transition_cache[0], (0, 0))
        elapsed = self.nav.transition_elapsed(time.monotonic())
        composed = self.nav.transition.frame(self.logical, elapsed)
        if composed is not self.logical:
            self.logical.blit(composed, (0, 0))
        pet_rect = self.pet_overlay.draw(self.logical, visible=self._pet_visible())
        # 首幀＝新畫面上場（chrome 可能整組換），全量；其後只有滑動帶在動
        from deskbar.ui.dashboard import CENTER_SLIDE_AREA as A
        dirty = None if first else self._union_dirty(
            (int(A.x), int(A.y), int(A.w), int(A.h)), pet_rect)
        self._flip(dirty)
        _frame, self._last_seq, self._last_minute, self._last_clock_text = \
            self.nav.transition_cache
        if not self.nav.transition.active():
            self.nav.clear_transition()

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
            # 待辦/便條牆：跟手拖曳放手後的吸附動畫；沒拖過門檻則觸發 dispatch 點擊
            if abs(dx) > DRAG_THRESHOLD and sx > TL_X0:
                from deskbar.ui.dashboard import CENTER_SLIDE_AREA
                r = pygame.Rect(int(CENTER_SLIDE_AREA.x), int(CENTER_SLIDE_AREA.y),
                                int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h))
                cur_page = self.center_pages.get(center, 0)
                if center == "linear":
                    from deskbar.ui import linearview
                    total = linearview.page_count(len(self.state.snapshot().linear))
                else:
                    from deskbar.ui import notesview
                    total = notesview.page_count(
                        len(self.notes_store.list()) if self.notes_store else 0)
                has_prev = cur_page > 0
                has_next = cur_page < total - 1

                if self._page_drag is None:
                    cur = self.logical.subsurface(r).copy() if getattr(self, "logical", None) is not None else None
                    drag = {
                        "center": center,
                        "cur": cur,
                        "neighbour": None,
                        "dir": -1 if dx < 0 else 1,
                        "has_prev": has_prev,
                        "has_next": has_next,
                        "rect": r,
                    }
                    drag.update(self._page_drag_rot_fields(cur, None, r))
                    self._page_drag = drag

                from_off = page_drag_offset(dx, r.w, has_prev, has_next)
                d = page_drag_decision(dx, r.w, has_prev, has_next)
                if d != 0:
                    self._flip_center_page(center, d)
                to_off = -r.w if d == 1 else (r.w if d == -1 else 0.0)
                self._page_settle = {
                    "from": from_off,
                    "to": to_off,
                    "start": time.monotonic(),
                    "drag": self._page_drag,
                }
            else:
                if self._page_drag is not None:
                    # 手指曾經拖過門檻又彈回點擊範圍時，結束暫存拖曳並強制重繪，
                    # 避免實機 _rot_cache 或 dev logical 留著半路拖曳畫面。
                    self._page_drag = None
                    self._rot_angle = None
                    self._last_seq = -1
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
                or self._drag_last is None or self.nav.transition_active()
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

    def _blit_page_band_rotated(self, drag: dict, off: float) -> None:
        """把待辦/便條牆拖曳快照依 off 合成到輸出面。

        實機路徑直接改 _rot_cache，避免 Pi Zero 2W 每幀重做 18.3ms 的帶狀旋轉；
        快一點的板子（Pi 4 旋轉約 3-5ms）可以刪掉這段妥協，退回下面 _dev 用的
        logical 合成後 _flip(rect) 寫法。因為這裡會把 _rot_cache 暫時改成拖曳畫面，
        吸附結束時必須讓下一次全量 _flip 重建快取，否則會殘留拖曳中的像素。
        """
        r = drag["rect"]
        cur = drag["cur"]
        neighbour = drag["neighbour"]
        drag_dir = drag["dir"]

        if self._dev or "cur_rot" not in drag:
            prev_clip = self.logical.get_clip()
            self.logical.set_clip(r)
            self.logical.fill(theme.C["bg"], r)
            self.logical.blit(cur, (int(r.x + off), r.y))
            if neighbour is not None:
                if drag_dir < 0:
                    self.logical.blit(neighbour, (int(r.x + off + r.w), r.y))
                else:
                    self.logical.blit(neighbour, (int(r.x + off - r.w), r.y))
            self.logical.set_clip(prev_clip)
            self._flip(r)
            return

        cur_rot = drag.get("cur_rot")
        angle = drag.get("angle")
        rot_base = drag.get("rot_base")
        if cur_rot is None or angle is None or rot_base is None:
            return
        if self._rot_cache is None or self._rot_angle != angle:
            # 正常 render loop 會保留 _rot_cache；測試或異常重入時補建一次，避免拋例外。
            self._rot_cache = pygame.transform.rotate(self.logical, angle)
            self._rot_angle = angle

        rot_rect = pygame.Rect(rot_base, cur_rot.get_size()).clip(self._rot_cache.get_rect())
        if rot_rect.w <= 0 or rot_rect.h <= 0:
            return

        ox, oy = rot_offset(off, angle)
        prev_clip = self._rot_cache.get_clip()
        self._rot_cache.set_clip(rot_rect)
        self._rot_cache.fill(theme.C["bg"], rot_rect)
        self._rot_cache.blit(cur_rot, (int(rot_base[0] + ox), int(rot_base[1] + oy)))

        neighbour_rot = drag.get("neighbour_rot")
        if neighbour_rot is not None:
            if drag_dir < 0:
                nox, noy = rot_offset(r.w, angle)
            else:
                nox, noy = rot_offset(-r.w, angle)
            self._rot_cache.blit(neighbour_rot,
                                 (int(rot_base[0] + ox + nox),
                                  int(rot_base[1] + oy + noy)))
        self._rot_cache.set_clip(prev_clip)

        if getattr(self, "screen", None) is not None:
            dst_rect = rot_rect.clip(self.screen.get_rect())
            if dst_rect.w > 0 and dst_rect.h > 0:
                veil = self._dim_veil(self._rot_cache.get_size())
                self.screen.blit(self._rot_cache, dst_rect.topleft, dst_rect)
                if veil is not None:
                    self.screen.blit(veil, dst_rect.topleft, dst_rect)
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            pygame.display.flip()

    def _prefetch_page_band_if_idle(self, snap, now) -> bool:
        # 2026-08-10 實機量測預取單次需 673ms，期間完全不處理輸入；必須先
        # 連續閒置 2 秒，確保昂貴工作落在使用者確實沒有操作的時候。
        mono = time.monotonic()
        if self._idle_since == 0.0:
            self._idle_since = mono
            return False
        if not should_prefetch(self._idle_since, mono, PREFETCH_IDLE_S):
            return False
        if not self._prefetch_page_band(snap, now):
            return False
        self._idle_since = time.monotonic()
        return True

    def _prefetch_page_band(self, snap, now) -> bool:
        """完全閒置時預畫一張相鄰頁帶狀快照；成功做事才回 True。

        2026-08-10 Pi Zero 2W 實測：便條牆相鄰頁熱渲染約 304／286／178ms，
        同步拖曳起手 507ms，但後續幀只要 13.3ms。這裡刻意每圈最多搬一頁
        （約 300ms）到沒有輸入的閒置時刻，避免一次畫兩頁造成約 600ms 停頓。
        預取只是最佳化；任何失敗都安靜略過，不能拖垮 render loop。
        """
        if (self.view != "dashboard"
                or getattr(self.settings, "center_view", "calendar") not in ("linear", "notes")
                or self._drag_start is not None
                or self._page_drag is not None
                or self._page_settle is not None
                or self.nav.transition_active()
                or self.firing
                or self.card_overlay is not None):
            return False

        center = self.settings.center_view
        try:
            if center == "linear":
                from deskbar.ui import linearview
                item_count = len(snap.linear)
                total = linearview.page_count(item_count)
            else:
                from deskbar.ui import notesview
                item_count = len(self.notes_store.list()) if self.notes_store else 0
                total = notesview.page_count(item_count)

            key = (center, snap.seq, item_count)
            if key != self._band_cache_key:
                self._band_cache.clear()
                self._band_cache_key = key

            raw_page = self.center_pages.get(center, 0)
            cur_page = max(0, min(total - 1, raw_page))
            neighbours = []
            if cur_page > 0:
                neighbours.append(cur_page - 1)
            if cur_page < total - 1:
                neighbours.append(cur_page + 1)
            target_page = next(
                (page for page in neighbours if (center, page) not in self._band_cache),
                None,
            )
            if target_page is None:
                return False

            from deskbar.ui.dashboard import CENTER_SLIDE_AREA
            r = pygame.Rect(int(CENTER_SLIDE_AREA.x), int(CENTER_SLIDE_AREA.y),
                            int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h))
            old_page = self.center_pages.get(center, 0)
            old_hits = self.hits
            original = self.logical.copy()
            band = None
            with self.pet_overlay.preserve_background():
                try:
                    self.center_pages[center] = target_page
                    self._draw_frame(snap, now, include_pet=False)
                    band = self.logical.subsurface(r).copy()
                finally:
                    # 離線畫鄰頁會改 logical 與 hits；兩者都要還原，使用者才不會看到
                    # 預取中的頁面，點擊區也仍對應目前頁。
                    self.center_pages[center] = old_page
                    self.hits = old_hits
                    self.logical.blit(original, (0, 0))

            self._band_cache[(center, target_page)] = band
            while len(self._band_cache) > 4:
                del self._band_cache[next(iter(self._band_cache))]
            return True
        except Exception:
            return False

    def _render_page_drag_band(self) -> None:
        """待辦/便條牆拖曳跟手：離線快照當前頁與鄰頁帶狀畫面，拖曳中 1:1 位移與節流 flip。

        第一版跟手是拖曳中逐幀全量重繪——Pi Zero 2W 一幀 100ms+，實際 8fps
        橡皮筋感（實機回報「非常不跟手的卡頓感」）。改成拖曳開始時快照中欄
        帶狀畫面與鄰頁，之後每幀只做一次帶狀 blit（幾 ms），內容跟著手指 1:1 移動。
        鄰頁通常已由閒置預取；沒命中才保留同步離線渲染作保底。只在 dashboard
        待辦／便條牆視圖生效。
        """
        if (self.view != "dashboard" or self._drag_start is None
                or self._drag_last is None or self.nav.transition_active()
                or self.firing or self.card_overlay is not None
                or getattr(self, "logical", None) is None):
            return
        center = getattr(self.settings, "center_view", "calendar")
        if center not in ("linear", "notes"):
            return
        from deskbar.ui.dashboard import CENTER_SLIDE_AREA, TL_X0
        sx, _sy = self._drag_start
        lx, _ly = self._drag_last
        if sx <= TL_X0 or abs(lx - sx) <= DRAG_THRESHOLD:
            return

        dx = lx - sx
        current_dir = -1 if dx < 0 else 1

        # 若拖曳方向中途反轉且超過門檻，清掉狀態讓下一幀重新建立（離線渲染另一側鄰頁）
        if self._page_drag is not None and self._page_drag["dir"] != current_dir:
            self._page_drag = None

        r = pygame.Rect(int(CENTER_SLIDE_AREA.x), int(CENTER_SLIDE_AREA.y),
                        int(CENTER_SLIDE_AREA.w), int(CENTER_SLIDE_AREA.h))

        if self._page_drag is None:
            cur = self.logical.subsurface(r).copy()
            cur_page = self.center_pages.get(center, 0)
            snap = self.state.snapshot()
            if center == "linear":
                from deskbar.ui import linearview
                item_count = len(snap.linear)
                total = linearview.page_count(item_count)
            else:
                from deskbar.ui import notesview
                item_count = len(self.notes_store.list()) if self.notes_store else 0
                total = notesview.page_count(item_count)
            key = (center, snap.seq, item_count)
            if key != self._band_cache_key:
                self._band_cache.clear()
                self._band_cache_key = key
            has_prev = cur_page > 0
            has_next = cur_page < total - 1

            neighbour = None
            target_page = cur_page + (1 if dx < 0 else -1)
            if (dx < 0 and has_next) or (dx > 0 and has_prev):
                neighbour = self._band_cache.get((center, target_page))
                if neighbour is None:
                    old_page = self.center_pages.get(center, 0)
                    with self.pet_overlay.preserve_background():
                        try:
                            self.center_pages[center] = target_page
                            from datetime import datetime
                            from zoneinfo import ZoneInfo
                            now = datetime.now(ZoneInfo("Asia/Taipei"))
                            self._draw_frame(snap, now, include_pet=False)
                            neighbour = self.logical.subsurface(r).copy()
                        except Exception:
                            # 同步保底也不能讓輸入圈拋例外；沒有鄰頁快照時仍可做邊界阻尼。
                            neighbour = None
                        finally:
                            self.center_pages[center] = old_page
                            self.logical.blit(cur, r.topleft)

            drag = {
                "center": center,
                "cur": cur,
                "neighbour": neighbour,
                "dir": current_dir,
                "has_prev": has_prev,
                "has_next": has_next,
                "rect": r,
            }
            drag.update(self._page_drag_rot_fields(cur, neighbour, r))
            self._page_drag = drag

        mono = time.monotonic()
        if mono - self._page_drag_at < PAN_BAND_INTERVAL_DRAG:
            return
        self._page_drag_at = mono

        has_prev = self._page_drag["has_prev"]
        has_next = self._page_drag["has_next"]

        off = page_drag_offset(dx, r.w, has_prev, has_next)
        self._blit_page_band_rotated(self._page_drag, off)

    def _render_page_settle_frame(self, now) -> None:
        """待辦/便條牆拖曳放手後的吸附動畫。

        動畫期間沿用 drag 時截下的 cur/neighbour 快照做帶狀 blit，
        位移量 offset 由時間內插（ease-out quad）。動畫結束後清除狀態並
        設定 _last_seq = -1 強制全量重繪。
        """
        if self._page_settle is None or getattr(self, "logical", None) is None:
            return
        elapsed = time.monotonic() - self._page_settle["start"]
        progress = elapsed / PAGE_SETTLE_S
        from_off = self._page_settle["from"]
        to_off = self._page_settle["to"]
        drag = self._page_settle["drag"]

        if progress >= 1.0:
            self._page_drag = None
            self._page_settle = None
            # 拖曳實機路徑會直接把 _rot_cache 改成暫時畫面；吸附完成後讓下一次
            # 全量 _flip 重建快取，避免拖曳殘影留在後續局部更新的基底裡。
            self._rot_angle = None
            self._last_seq = -1
            self._render()
            return

        ease_p = 1.0 - (1.0 - progress) ** 2
        off = from_off + (to_off - from_off) * ease_p

        self._blit_page_band_rotated(drag, off)


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
        if self.view != "dashboard" or self.nav.transition_active():
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
            switch = self.scene_controller.imminent_switch(
                current_center=cur,
                soon=soon,
                view=self.view,
                transition_active=self.nav.transition_active(),
            )
            if switch is not None:
                self.settings.center_view = switch.center_view
        if switch is not None:
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

    def _finish_pet_drag(self, x: int, y: int) -> None:
        position = self.pet_overlay.finish_drag(x, y)
        if position is None:
            return
        pet_x, pet_y = position
        with self.lock:
            self.settings.pet_x = pet_x
            self.settings.pet_y = pet_y
            self.on_save(self.settings)
        self._last_seq = -1

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
        平常＝記下拖曳起點＋狀態重置＋立即畫按壓高亮。"""
        if self._page_settle is not None or self._page_drag is not None:
            # 新觸控會中斷上一段拖曳；實機路徑可能已改過 _rot_cache，先失效化，
            # 讓後續按壓高亮的局部 _flip 不會拿拖曳暫存畫面當基底。
            self._rot_angle = None
        self._page_settle = None
        self._page_drag = None
        if self._screen_asleep():
            self._wake_until = time.monotonic() + WAKE_SECONDS
            self._swallow_touch = True
            self._drag_start = None
            self._last_seq = -1     # 立刻重繪＝亮回來
            return
        if not self.firing and self.pet_overlay.begin_drag(
                x, y, visible=self._pet_visible()):
            self._drag_start = None
            self._drag_last = None
            self._pressed_dirty = False
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
                if self.pet_overlay.dragging:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self.pet_overlay.drag_to(x, y)
                elif self._drag_start is not None:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    self._drag_last = (x, y)
            elif ev.type == pygame.FINGERUP:
                had_input = True
                if self._swallow_touch:
                    self._swallow_touch = False
                else:
                    x, y = transform.touch_to_logical(ev.x, ev.y, self.settings.rotation)
                    if self.pet_overlay.dragging:
                        self._finish_pet_drag(x, y)
                    else:
                        self._handle_touch_up(x, y)
            elif ev.type == pygame.MOUSEBUTTONDOWN:   # dev 模式滑鼠模擬觸控
                had_input = True
                x, y = transform.dev_window_to_logical(
                    ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                self._touch_down(x, y)
            elif ev.type == pygame.MOUSEMOTION:
                if self.pet_overlay.dragging:
                    had_input = True
                    x, y = transform.dev_window_to_logical(
                        ev.pos[0], ev.pos[1], self.win[0], self.win[1], self._dev_rotate or 0)
                    self.pet_overlay.drag_to(x, y)
                elif self._drag_start is not None:
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
                    if self.pet_overlay.dragging:
                        self._finish_pet_drag(x, y)
                    else:
                        self._handle_touch_up(x, y)
        if had_input:
            self._idle_since = 0.0
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        if self.pet_overlay.dragging:
            self._render_pet_tick(now, force=True)
            clock.tick(loop_fps(True))
            return running
        if self._drag_start is not None:
            # 跟手位移每圈只做一次（motion 事件常一圈湧進 3-5 顆，逐顆 flip 白燒）
            self._pan_band_preview()
            self._render_page_drag_band()
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
        if self.nav.transition_active():    # 切換過場優先於翻牌動畫（兩者不會同時發生）
            self._render_transition_frame(now)
            clock.tick(30)
            return running
        if self._page_settle is not None:
            self._render_page_settle_frame(now)
            clock.tick(loop_fps(True))
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
            # 久坐追蹤：每輪迴圈餵一次在場狀態；提示出現/消失那一拍主動重繪
            # （靠 seq/分鐘變化最多晚 60 秒才畫出來，邊緣觸發才即時）
            mono = time.monotonic()
            if snap.presence.enabled:
                self.sedentary.update(snap.presence.present, mono)
            else:
                self.sedentary.reset()
            sed_hint = self.sedentary.hint_active(mono)
            if sed_hint != self._sed_hint_last:
                self._sed_hint_last = sed_hint
                self._render()
            # 忙/閒中欄排程：usage 增量餵活動偵測，每 15 秒評估一次目標視圖
            self.usage_activity.feed(snap.usage, mono)
            mode = getattr(self.settings, "scene_mode", "auto")
            if mode == "auto" and mono - self._flow_check_at >= 15:
                self._flow_check_at = mono
                self._check_flow_center(mono)
            elif mode == "force":
                self._check_force_scene(mono)
            if self._screen_asleep():
                # 深夜熄屏：不燒氛圍幀、輪詢降到 2fps（整夜 15fps 畫給黑幕看
                # 純屬浪費）；觸摸喚醒那一圈 had_input=True 立即提速。
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
            elif self._drag_start is not None or self._page_settle is not None:
                # 跟手拖曳／吸附時帶狀 blit 已在迴圈前段完成，不需全量重繪。
                # 2026-08-10 Pi Zero 2W 實測單圈工作 13.7ms，tick(30) 卻讓
                # 每圈變成 33.2ms；改為 60fps 才不會用約 20ms 睡眠拖慢跟手。
                clock.tick(loop_fps(True))
            elif snap.seq != self._last_seq or now.minute != self._last_minute:
                self._render()
                clock.tick(30)
            elif (self._ambient_active(snap) or self._scene_active()) \
                    and not had_input:
                # 資料/分鐘都沒變，但天氣場景要動：左欄局部重繪，幀率按場景分級。
                # 歷史教訓（2026-07-27「根本看不到動畫」）：這裡以前只有上面那條
                # 全量重繪，天氣 tick 每秒都在加、畫面卻一分鐘才畫一次。
                # had_input 時讓路給輸入處理（例如跟手預覽剛全量重繪過）。
                self._render_ambient(snap, now)
                from deskbar.ui import scenes, weatherfx
                fps = weatherfx.ambient_fps(snap.weather.code) \
                    if self._ambient_active(snap) else 0
                if self._scene_active():
                    fps = max(fps, scenes.FPS)
                clock.tick(fps)
            elif self._render_pet_tick(now):
                clock.tick(self.pet_overlay.fps)
            else:
                # 純閒置輪詢從 10fps 提到 30fps：一次觸控最慢 100ms 後才被看見，
                # 是延遲感的最大單一來源。空圈只做事件泵＋幾個判斷，30fps 的
                # CPU 成本 <3%，換來輸入延遲上限 33ms。
                if not had_input:
                    self._prefetch_page_band_if_idle(snap, now)
                clock.tick(30)
        return running
