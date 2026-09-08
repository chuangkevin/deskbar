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
        if email.startswith("work"):
            # 10 分鐘後開始：本機一開就能看到左欄倒數、迫近脈動與自動搶焦點
            events.append(Event(f"{email}-soon", email, "c", "迫近測試會議",
                                now + timedelta(minutes=10),
                                now + timedelta(minutes=40), False, None, None))
        state.set_events(email, events, now)
    # dev 假天氣預設 code 80（陣雨）——刻意讓雨刷/玻璃層常駐展示；
    # 想看別的場景：DESKBAR_FAKE_WEATHER=0 晴 / 3 陰 / 95 雷雨 / 71 雪
    fake_code = int(os.environ.get("DESKBAR_FAKE_WEATHER", "80"))
    state.set_weather(Weather(33.4, fake_code, 34.1, 26.3, settings.weather_label, now))
    # 假待辦（真環境由 linear_loop 同步；FAKE 模式不開同步執行緒）：
    # 兩頁的量，翻頁/詳情浮層/右欄摘要都測得到
    from deskbar.linear import LinearIssue
    colors = ["#f2994a", "#5e6ad2", "#0f7488", "#4cb782", "#95a2b3"]
    states = [("In Progress", "started"), ("Todo", "unstarted"), ("Backlog", "backlog")]
    fake_linear = []
    for i in range(11):
        sn, st_ = states[i % 3]
        fake_linear.append(LinearIssue(
            identifier=f"DEMO-{101 + i}",
            title=["修正排程器時區漂移", "客服工單匯出 CSV", "部署腳本加健康檢查",
                   "重構通知服務", "使用者權限盤點", "升級資料庫驅動",
                   "看板卡片拖曳優化", "API 錯誤碼標準化", "壓測報告整理",
                   "行動版排版跑版", "檢查備援還原流程"][i],
            state_name=sn, state_type=st_, state_color=colors[i % 5],
            priority=[1, 2, 2, 3, 0][i % 5],
            due=now.date() + timedelta(days=[-1, 0, 2, 7, 30][i % 5])
            if i % 4 else None, project="SARA"))
    state.set_linear(fake_linear, now)
    settings.linear_api_key = settings.linear_api_key or "demo"   # 讓待辦牆不顯示「未連接」


def main() -> None:
    settings = config.load_settings()
    from deskbar.ui import theme
    theme.set_theme(settings.theme)   # 一定要在 App._init_display()／pygame.init() 之前
    state = AppState(config.config_dir() / "usage_sources.json")
    state.load_cache()
    from deskbar import linear as _linear
    _cached_items, _cached_at = _linear.load_cache()
    if _cached_items:
        state.set_linear(_cached_items, _cached_at)
    lock = threading.Lock()
    if os.environ.get("DESKBAR_FAKE") == "1":
        _fake_data(state, settings)
    else:
        from deskbar import sync
        sync.start_threads(state, settings, lock)

    from deskbar.presence import start_presence_thread
    start_presence_thread(state, settings, lock)   # 永遠啟動；迴圈每輪自查 enabled/mac 就自動跳過

    from deskbar.alarms import AlarmStore
    alarm_store = AlarmStore()
    alarm_store.load()
    from deskbar.notes import NotesStore
    notes_store = NotesStore()
    notes_store.load()
    # /api/screenshot 的跨執行緒橋：webserver 設 want、render 迴圈拍完設 done
    shot_bridge = {"want": threading.Event(), "done": threading.Event(), "data": None}
    if os.environ.get("DESKBAR_NO_WEB") != "1":
        from deskbar.webserver import start_web
        start_web(alarm_store, settings_provider=settings, settings_lock=lock,
                  on_save=config.save_settings, usage_state=state,
                  notes_store=notes_store, shot_bridge=shot_bridge)

    app = App(state, settings, lock, on_save=config.save_settings,
              alarm_store=alarm_store, notes_store=notes_store,
              shot_bridge=shot_bridge)
    app.run()


if __name__ == "__main__":
    main()
