import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LAT, DEFAULT_LON, DEFAULT_LABEL = 25.046, 121.517, "台北"
VALID_VIEW_SPANS = {"half", "day", "week", "month"}
VALID_VIEW_MODES = {"lanes", "agenda"}
VALID_THEMES = {"dark", "light"}


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
        presence_interval_sec = raw.get("presence_interval_sec", 45)
        if not isinstance(presence_interval_sec, int) \
                or isinstance(presence_interval_sec, bool) \
                or not (5 <= presence_interval_sec <= 600):
            presence_interval_sec = 45
        return Settings(
            rotation=raw.get("rotation", 90),
            weather_lat=raw.get("weather_lat", DEFAULT_LAT),
            weather_lon=raw.get("weather_lon", DEFAULT_LON),
            weather_label=raw.get("weather_label", DEFAULT_LABEL),
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
        )
    except (OSError, ValueError, KeyError, TypeError):
        return Settings()


def save_settings(s: Settings) -> None:
    data = {
        "rotation": s.rotation,
        "weather_lat": s.weather_lat,
        "weather_lon": s.weather_lon,
        "weather_label": s.weather_label,
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
        "accounts": {
            e: {"lane_label": a.lane_label, "color": a.color, "calendars": a.calendars}
            for e, a in s.accounts.items()
        },
    }
    fd, tmp = tempfile.mkstemp(dir=config_dir(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())
