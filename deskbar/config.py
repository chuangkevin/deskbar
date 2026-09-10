import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LAT, DEFAULT_LON, DEFAULT_LABEL = 25.046, 121.517, "台北"
# 氛圍場景清單（ui/scenes.py 的 registry 與此同步；config 是唯一來源，
# 讓 webserver/web 不必 import pygame 就能驗證）
SCENE_KEYS = (
    "flow", "stars", "ridges", "fireflies", "fish", "aurora", "train",
    "runner", "ink", "planet_horizon", "glass_rain", "magnetic_fog",
    "reverse_lightning", "tidal_aurora",
)
# 新場景一律先產晨／晝／夜驗證圖，經使用者確認才加入這份預設輪播。
# 2026-08-04 實機複審後只保留目前仍獲核可的場景；其餘場景可手動選取驗收，
# 但在美術與動態再次通過前不得進入預設輪播。
DEFAULT_SCENES = (
    "stars", "planet_horizon", "glass_rain", "magnetic_fog",
    "reverse_lightning", "tidal_aurora",
)
VALID_VIEW_SPANS = {"half", "day", "week", "month"}
VALID_VIEW_MODES = {"lanes", "agenda"}
VALID_THEMES = {"dark", "light"}
VALID_USAGE_SOURCES = ("claude", "antigravity", "openai")
DEFAULT_PET_X, DEFAULT_PET_Y = 1660, 300


def normalize_usage_sources(value, default=VALID_USAGE_SOURCES) -> tuple[str, ...]:
    """回傳可儲存的用量來源清單。

    舊設定沒有這個欄位時維持原本三個都顯示；空清單則是使用者明確選擇
    完全不顯示。設定檔若被手動寫壞，寧可安全退回預設，不讓右欄因未知
    provider 進入不一致狀態。
    """
    # tuple 是 Settings 的 in-memory 表示；JSON 設定檔讀進來則必為 list。
    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
        return tuple(default)
    if any(x not in VALID_USAGE_SOURCES for x in value):
        return tuple(default)
    return tuple(key for key in VALID_USAGE_SOURCES if key in value)


def normalize_oa_aliases(value, default=None) -> dict[str, str]:
    if default is None:
        default = {}
    if not isinstance(value, dict) or len(value) > 8:
        return dict(default)
    aliases = {}
    for account_id, alias in value.items():
        if not isinstance(account_id, str) or not account_id.strip() or not isinstance(alias, str):
            return dict(default)
        normalized_alias = alias.strip()
        if len(normalized_alias) > 24:
            return dict(default)
        if normalized_alias:
            aliases[account_id.strip()] = normalized_alias
    return aliases


def normalize_oa_hidden(value, default=None) -> tuple[str, ...]:
    if default is None:
        default = ()
    if not isinstance(value, (list, tuple)) or len(value) > 8:
        return tuple(default)
    hidden = []
    seen = set()
    for account_id in value:
        if not isinstance(account_id, str) or not account_id.strip():
            return tuple(default)
        normalized = account_id.strip()
        if normalized not in seen:
            hidden.append(normalized)
            seen.add(normalized)
    return tuple(hidden)


def config_dir() -> Path:
    d = Path(os.environ.get("DESKBAR_CONFIG_DIR", Path.home() / ".config" / "deskbar"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = Path(os.environ.get("DESKBAR_CACHE_DIR", Path.home() / ".cache" / "deskbar"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def accounts_dir() -> Path:
    d = config_dir() / "accounts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class AccountCfg:
    lane_label: str
    color: int
    calendars: dict[str, bool] = field(default_factory=dict)


@dataclass
class Settings:
    rotation: int = 90
    weather_lat: float = DEFAULT_LAT
    weather_lon: float = DEFAULT_LON
    weather_label: str = DEFAULT_LABEL
    weather_auto_locate: bool = True    # IP 定位自動跟隨裝置位置（換網路即換城市）
    weather_metar_station: str = "RCSS"  # 空字串＝停用 METAR，純用 Open-Meteo
    start_hour: int = 8
    end_hour: int = 24
    sync_interval_min: int = 5
    view_span: str = "day"
    view_mode: str = "lanes"
    theme: str = "dark"
    accounts: dict[str, AccountCfg] = field(default_factory=dict)
    presence_enabled: bool = False
    presence_mac: str = ""
    presence_rssi_threshold: int = -75
    presence_hide_accounts: list[str] = field(default_factory=list)
    presence_grace_sec: int = 150
    presence_interval_sec: int = 45     # 藍牙探測間隔；設定頁「感應速度」快/中/慢連動
    presence_source: str = "bluetooth"  # "bluetooth" | "push" | "ble" (2026-08-06 擴充 BLE 掃描)
    presence_push_ttl_sec: int = 900    # push 多久沒來就視為不在場
    work_start_min: int = 540           # 上班開始（分鐘制 0-1439）；螢幕亮度排程用
    work_end_min: int = 1080            # 下班（分鐘制）；此後套用下班亮度
    brightness_day: int = 100           # 上班時段亮度 %（軟體疊黑實現）
    brightness_night: int = 40          # 下班時段亮度 %
    sleep_enabled: bool = False         # 深夜熄屏（睡眠時段全黑，觸摸喚醒 30 秒）
    sleep_start_min: int = 60           # 睡眠開始 01:00（分鐘制）
    sleep_end_min: int = 390            # 睡眠結束 06:30
    linear_api_key: str = ""            # Linear 個人 API Key（只存裝置，不進 repo/log）
    center_view: str = "calendar"       # 中欄顯示：calendar｜linear（待辦）｜notes（便條）｜sessions（工作）｜scene（場景）
    scene_mode: str = "auto"            # 場景進入方式：auto（忙閒排程）｜manual｜force
    scenes_enabled: tuple = DEFAULT_SCENES  # 要輪播的場景（網頁勾選）
    usage_sources: tuple[str, ...] = VALID_USAGE_SOURCES  # 右欄要顯示的 AI 用量來源
    pet_enabled: bool = True            # 小喜喜桌面寵物（全域 overlay，非場景）
    pet_x: int = DEFAULT_PET_X          # 小喜喜左上角 logical x（拖曳後持久化）
    pet_y: int = DEFAULT_PET_Y          # 小喜喜左上角 logical y
    oa_aliases: dict[str, str] = field(default_factory=dict)  # OpenAI account_id -> 使用者別名
    oa_hidden: tuple[str, ...] = ()      # 不顯示的 OpenAI account_id；新帳號預設顯示

    def ensure_account(self, email: str) -> AccountCfg:
        if email not in self.accounts:
            used = {a.color for a in self.accounts.values()}
            color = next(i for i in range(16) if i not in used)
            self.accounts[email] = AccountCfg(lane_label=email.split("@")[0], color=color)
        return self.accounts[email]


def _path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> Settings:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        accounts = {
            e: AccountCfg(a["lane_label"], a["color"], dict(a.get("calendars", {})))
            for e, a in raw.get("accounts", {}).items()
        }
        view_span = raw.get("view_span", "day")
        if view_span not in VALID_VIEW_SPANS:
            view_span = "day"
        view_mode = raw.get("view_mode", "lanes")
        if view_mode not in VALID_VIEW_MODES:
            view_mode = "lanes"
        theme = raw.get("theme", "dark")
        if theme not in VALID_THEMES:
            theme = "dark"
        sync_interval_min = raw.get("sync_interval_min", 5)
        if not isinstance(sync_interval_min, int) or isinstance(sync_interval_min, bool) \
                or not (1 <= sync_interval_min <= 120):
            sync_interval_min = 5
        presence_enabled = raw.get("presence_enabled", False)
        if not isinstance(presence_enabled, bool):
            presence_enabled = False
        presence_mac = raw.get("presence_mac", "")
        if not isinstance(presence_mac, str):
            presence_mac = ""
        presence_rssi_threshold = raw.get("presence_rssi_threshold", -75)
        if not isinstance(presence_rssi_threshold, int) \
                or isinstance(presence_rssi_threshold, bool):
            presence_rssi_threshold = -75
        presence_hide_accounts = raw.get("presence_hide_accounts", [])
        if not isinstance(presence_hide_accounts, list) \
                or not all(isinstance(x, str) for x in presence_hide_accounts):
            presence_hide_accounts = []
        presence_grace_sec = raw.get("presence_grace_sec", 150)
        if not isinstance(presence_grace_sec, int) or isinstance(presence_grace_sec, bool) \
                or presence_grace_sec < 0:
            presence_grace_sec = 150
        # 2026-08-04 實機事故：單次探測最壞是 l2ping 5 秒＋hcitool rssi 5 秒＝10 秒，
        # 間隔比它短等於保證重疊送連線請求打死 BCM43438 控制器，故下限拉高至 20 秒。
        presence_interval_sec = raw.get("presence_interval_sec", 45)
        if not isinstance(presence_interval_sec, int) \
                or isinstance(presence_interval_sec, bool) \
                or not (20 <= presence_interval_sec <= 600):
            presence_interval_sec = 45

        presence_source = raw.get("presence_source", "bluetooth")
        if not isinstance(presence_source, str) or presence_source not in ("bluetooth", "push", "ble"):
            presence_source = "bluetooth"

        presence_push_ttl_sec = raw.get("presence_push_ttl_sec", 900)
        if not isinstance(presence_push_ttl_sec, int) \
                or isinstance(presence_push_ttl_sec, bool) \
                or not (60 <= presence_push_ttl_sec <= 86400):
            presence_push_ttl_sec = 900

        def _int_in(key, default, lo, hi):
            v = raw.get(key, default)
            if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
                return default
            return v

        def _min_from(new_key, old_key, default_min):
            # 新欄位優先；讀得到舊的「小時制」欄位就 ×60 遷移（2026-07-27 改制）。
            v = raw.get(new_key)
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1439:
                return v
            old = raw.get(old_key)
            if isinstance(old, int) and not isinstance(old, bool) and 0 <= old <= 23:
                return old * 60
            return default_min

        work_start_min = _min_from("work_start_min", "work_start_hour", 540)
        work_end_min = _min_from("work_end_min", "work_end_hour", 1080)
        brightness_day = _int_in("brightness_day", 100, 10, 100)
        brightness_night = _int_in("brightness_night", 40, 10, 100)
        weather_auto_locate = raw.get("weather_auto_locate", True)
        if not isinstance(weather_auto_locate, bool):
            weather_auto_locate = True
        weather_metar_station = raw.get("weather_metar_station", "RCSS")
        if not isinstance(weather_metar_station, str) or len(weather_metar_station) > 8:
            weather_metar_station = "RCSS"
        sleep_enabled = raw.get("sleep_enabled", False)
        if not isinstance(sleep_enabled, bool):
            sleep_enabled = False
        sleep_start_min = _int_in("sleep_start_min", 60, 0, 1439)
        sleep_end_min = _int_in("sleep_end_min", 390, 0, 1439)
        linear_api_key = raw.get("linear_api_key", "")
        if not isinstance(linear_api_key, str):
            linear_api_key = ""
        center_view = raw.get("center_view", "calendar")
        if center_view not in ("calendar", "linear", "notes", "sessions", "scene"):
            center_view = "calendar"
        scene_mode = raw.get("scene_mode", "auto")
        if scene_mode not in ("auto", "manual", "force"):
            scene_mode = "auto"
        se_raw = raw.get("scenes_enabled", list(DEFAULT_SCENES))
        scenes_enabled = tuple(k for k in SCENE_KEYS
                               if isinstance(se_raw, list) and k in se_raw) \
            or DEFAULT_SCENES           # 全被反勾＝退回預設（空清單無意義）
        usage_sources = normalize_usage_sources(
            raw.get("usage_sources", list(VALID_USAGE_SOURCES)))
        oa_aliases = normalize_oa_aliases(raw.get("oa_aliases", {}))
        oa_hidden = normalize_oa_hidden(raw.get("oa_hidden", ()))
        pet_enabled = raw.get("pet_enabled", True)
        if not isinstance(pet_enabled, bool):
            pet_enabled = True
        pet_x = _int_in("pet_x", DEFAULT_PET_X, 0, 1919)
        pet_y = _int_in("pet_y", DEFAULT_PET_Y, 0, 479)
        return Settings(
            rotation=raw.get("rotation", 90),
            weather_lat=raw.get("weather_lat", DEFAULT_LAT),
            weather_lon=raw.get("weather_lon", DEFAULT_LON),
            weather_label=raw.get("weather_label", DEFAULT_LABEL),
            weather_auto_locate=weather_auto_locate,
            weather_metar_station=weather_metar_station,
            start_hour=raw.get("start_hour", 8),
            end_hour=raw.get("end_hour", 24),
            sync_interval_min=sync_interval_min,
            view_span=view_span,
            view_mode=view_mode,
            theme=theme,
            accounts=accounts,
            presence_enabled=presence_enabled,
            presence_mac=presence_mac,
            presence_rssi_threshold=presence_rssi_threshold,
            presence_hide_accounts=presence_hide_accounts,
            presence_grace_sec=presence_grace_sec,
            presence_interval_sec=presence_interval_sec,
            presence_source=presence_source,
            presence_push_ttl_sec=presence_push_ttl_sec,
            work_start_min=work_start_min,
            work_end_min=work_end_min,
            brightness_day=brightness_day,
            brightness_night=brightness_night,
            sleep_enabled=sleep_enabled,
            sleep_start_min=sleep_start_min,
            sleep_end_min=sleep_end_min,
            linear_api_key=linear_api_key,
            center_view=center_view,
            scene_mode=scene_mode,
            scenes_enabled=scenes_enabled,
            usage_sources=usage_sources,
            pet_enabled=pet_enabled,
            pet_x=pet_x,
            pet_y=pet_y,
            oa_aliases=oa_aliases,
            oa_hidden=oa_hidden,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return Settings()


def save_settings(s: Settings) -> None:
    data = {
        "rotation": s.rotation,
        "weather_lat": s.weather_lat,
        "weather_lon": s.weather_lon,
        "weather_label": s.weather_label,
        "weather_auto_locate": s.weather_auto_locate,
        "weather_metar_station": s.weather_metar_station,
        "start_hour": s.start_hour,
        "end_hour": s.end_hour,
        "sync_interval_min": s.sync_interval_min,
        "view_span": s.view_span,
        "view_mode": s.view_mode,
        "theme": s.theme,
        "presence_enabled": s.presence_enabled,
        "presence_mac": s.presence_mac,
        "presence_rssi_threshold": s.presence_rssi_threshold,
        "presence_hide_accounts": s.presence_hide_accounts,
        "presence_grace_sec": s.presence_grace_sec,
        "presence_interval_sec": s.presence_interval_sec,
        "presence_source": s.presence_source,
        "presence_push_ttl_sec": s.presence_push_ttl_sec,
        "work_start_min": s.work_start_min,
        "work_end_min": s.work_end_min,
        "brightness_day": s.brightness_day,
        "brightness_night": s.brightness_night,
        "sleep_enabled": s.sleep_enabled,
        "sleep_start_min": s.sleep_start_min,
        "sleep_end_min": s.sleep_end_min,
        "linear_api_key": s.linear_api_key,
        "center_view": s.center_view,
        "scene_mode": s.scene_mode,
        "scenes_enabled": list(s.scenes_enabled),
        "usage_sources": list(normalize_usage_sources(s.usage_sources)),
        "oa_aliases": normalize_oa_aliases(s.oa_aliases),
        "oa_hidden": list(normalize_oa_hidden(s.oa_hidden)),
        "pet_enabled": s.pet_enabled,
        "pet_x": int(s.pet_x),
        "pet_y": int(s.pet_y),
        "accounts": {
            e: {"lane_label": a.lane_label, "color": a.color, "calendars": a.calendars}
            for e, a in s.accounts.items()
        },
    }
    fd, tmp = tempfile.mkstemp(dir=config_dir(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())
