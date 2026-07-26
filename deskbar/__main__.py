import os
import threading

from deskbar import config
from deskbar.store import AppState
from deskbar.ui.app import App


def _fake_data(state: AppState, settings) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from deskbar.models import Event
    from deskbar.weather import Weather
    tz = ZoneInfo("Asia/Taipei")
    now = datetime.now(tz)
    day = now.replace(minute=0, second=0, microsecond=0)
    for email, label, evs in [
        ("work@example.com", "工作", [("週會", 10, 11), ("設計討論", 13, 14)]),
        ("me@example.com", "個人", [("回診", 14, 15), ("家庭聚餐", 19, 21)]),
    ]:
        acc = settings.ensure_account(email)
        acc.lane_label = label
        events = [Event(f"{email}-{t}", email, "c", t,
                        day.replace(hour=h1), day.replace(hour=h2), False, "地點", "備註")
                  for t, h1, h2 in evs]
        events.append(Event(f"{email}-ad", email, "c", "整日事項",
                            day.replace(hour=0), day.replace(hour=0) + timedelta(days=1),
                            True, None, None))
        state.set_events(email, events, now)
    state.set_weather(Weather(33.4, 80, 34.1, 26.3, settings.weather_label, now))


def main() -> None:
    settings = config.load_settings()
    state = AppState()
    state.load_cache()
    lock = threading.Lock()
    if os.environ.get("DESKBAR_FAKE") == "1":
        _fake_data(state, settings)
    else:
        from deskbar import sync
        sync.start_threads(state, settings, lock)

    from deskbar.claudeusage import start_usage_thread
    start_usage_thread(state)      # 沒有 claude_oauth.json（沒跑過 claude-login）就直接跳過

    from deskbar.presence import start_presence_thread
    start_presence_thread(state, settings, lock)   # 沒設定 presence_enabled/mac 就自動跳過

    from deskbar.alarms import AlarmStore
    alarm_store = AlarmStore()
    alarm_store.load()
    if os.environ.get("DESKBAR_NO_WEB") != "1":
        from deskbar.webserver import start_web
        start_web(alarm_store, settings_provider=settings, settings_lock=lock,
                  on_save=config.save_settings)

    app = App(state, settings, lock, on_save=config.save_settings,
              alarm_store=alarm_store)
    app.run()


if __name__ == "__main__":
    main()
