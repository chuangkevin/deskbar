"""渲染驗證矩陣：載入真實行事曆資料，把 span×mode×anchor 全排列，加上設定頁／
鬧鐘頁／詳情浮層／鬧鐘觸發／同步中／帳號失效等特殊畫面，各存一張 PNG，供人眼
逐張核對頂欄／月視圖等版面改動在各種真實資料量下有沒有露出重疊或破版。

固定 NOW（2026-07-26 21:30 Asia/Taipei）確保每次重跑輸出可重現，方便用
git diff / 圖片比對工具追蹤某次改動實際造成了哪些畫面差異。

用法：
    .venv/bin/python tools/render_matrix.py --events /tmp/pi-events.json --out /tmp/matrix

headless：SDL_VIDEODRIVER 在 import pygame 之前就設成 dummy，不需要真的顯示器、
也不需要在 Pi 上跑——純渲染到 Surface 再存檔，跟 tests/conftest.py 的做法一致。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from deskbar.alarms import Alarm  # noqa: E402
from deskbar.config import Settings  # noqa: E402
from deskbar.models import event_from_json  # noqa: E402
from deskbar.store import AppState  # noqa: E402
from deskbar.ui import alarm_overlay, alarm_view, dashboard, detail, settings_view  # noqa: E402

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 26, 21, 30, tzinfo=TZ)   # 固定「現在」，確保輸出可重現

SPANS = ["half", "day", "week", "month"]
MODES = ["lanes", "agenda"]
ANCHORS = [
    ("none", None),
    ("minus3d", NOW - timedelta(days=3)),
    ("plus7d", NOW + timedelta(days=7)),
]


def _surface() -> "pygame.Surface":
    return pygame.Surface((1920, 480))


def _save(surface: "pygame.Surface", out_dir: Path, name: str, manifest: list[str]) -> None:
    path = out_dir / f"{name}.png"
    pygame.image.save(surface, str(path))
    manifest.append(str(path))


def load_state_and_settings(events_path: Path) -> tuple[AppState, Settings]:
    """/tmp/pi-events.json 的格式跟 AppState.save_cache() 輸出一致（email →
    event_to_json 清單），直接用 event_from_json 還原即可，不必另外轉格式。"""
    raw = json.loads(events_path.read_text(encoding="utf-8"))
    settings = Settings()
    state = AppState()
    for email, items in raw.items():
        events = [event_from_json(d) for d in items]
        acc = settings.ensure_account(email)
        for e in events:
            acc.calendars.setdefault(e.calendar_id, True)
        state.set_events(email, events, NOW)
    return state, settings


def render_matrix(state: AppState, settings: Settings, out_dir: Path) -> list[str]:
    """span×mode×anchor 全排列＝4×2×3＝24 張。"""
    manifest: list[str] = []
    snap = state.snapshot()
    for span in SPANS:
        for mode in MODES:
            for anchor_name, anchor in ANCHORS:
                settings.view_span = span
                settings.view_mode = mode
                surf = _surface()
                dashboard.render(surf, snap, settings, NOW, anchor=anchor)
                _save(surf, out_dir, f"span-{span}_mode-{mode}_anchor-{anchor_name}", manifest)
    return manifest


def render_settings_pages(state: AppState, settings: Settings, out_dir: Path) -> list[str]:
    """設定頁：確認條關／開各一張。"""
    manifest: list[str] = []
    snap = state.snapshot()
    accounts = list(settings.accounts)
    target = accounts[-1] if accounts else None

    surf = _surface()
    settings_view.render(surf, snap, settings, None)
    _save(surf, out_dir, "settings_confirm-off", manifest)

    surf = _surface()
    settings_view.render(surf, snap, settings, target)
    _save(surf, out_dir, "settings_confirm-on", manifest)
    return manifest


class _FixedAlarmStore:
    """render_matrix 專用的最小 AlarmStore 替身：不落地、只回傳固定清單，
    純粹為了餵給 alarm_view.render()（它只呼叫 store.list()）。"""

    def __init__(self, alarms: list[Alarm]):
        self._alarms = alarms

    def list(self) -> list[Alarm]:
        return self._alarms


def render_alarm_pages(out_dir: Path) -> list[str]:
    """鬧鐘頁：空清單／兩筆各一張。"""
    manifest: list[str] = []
    draft = {"hour": (NOW.hour + 1) % 24, "minute": 0, "days": set(), "label_idx": 0}

    surf = _surface()
    alarm_view.render(surf, _FixedAlarmStore([]), draft, NOW)
    _save(surf, out_dir, "alarms_empty", manifest)

    two = [
        Alarm(id="a1", time="07:30", days=[0, 1, 2, 3, 4], label="打卡", enabled=True),
        Alarm(id="a2", time="21:30", days=[], label="吃藥", enabled=False),
    ]
    surf = _surface()
    alarm_view.render(surf, _FixedAlarmStore(two), draft, NOW)
    _save(surf, out_dir, "alarms_two", manifest)
    return manifest


def render_detail_overlay(state: AppState, settings: Settings, out_dir: Path) -> list[str]:
    """詳情浮層：疊在 day/lanes 的 dashboard 背景上，挑一筆有描述的真實事件驗證截斷。"""
    manifest: list[str] = []
    snap = state.snapshot()
    with_desc = [e for e in snap.events if not e.all_day and e.description]
    event = with_desc[0] if with_desc else snap.events[0]

    settings.view_span = "day"
    settings.view_mode = "lanes"
    surf = _surface()
    dashboard.render(surf, snap, settings, NOW)
    detail.render(surf, event)
    _save(surf, out_dir, "detail_overlay", manifest)
    return manifest


def render_alarm_firing(out_dir: Path) -> list[str]:
    """鬧鐘觸發覆疊：alarm_overlay 是全螢幕閃爍畫面，跟 dashboard 背景無關。"""
    manifest: list[str] = []
    alarm = Alarm(id="fire1", time="21:30", days=[], label="會議提醒", enabled=True)
    surf = _surface()
    alarm_overlay.render(surf, alarm, NOW)
    _save(surf, out_dir, "alarm_firing_overlay", manifest)
    return manifest


def render_syncing(state: AppState, settings: Settings, out_dir: Path) -> list[str]:
    """同步中狀態：左下角同步狀態列顯示「同步中…」。"""
    manifest: list[str] = []
    state.set_syncing(True)
    snap = state.snapshot()
    settings.view_span = "day"
    settings.view_mode = "lanes"
    surf = _surface()
    dashboard.render(surf, snap, settings, NOW)
    _save(surf, out_dir, "dashboard_syncing", manifest)
    state.set_syncing(False)
    return manifest


def render_empty_states(out_dir: Path) -> list[str]:
    """agenda／month 的空資料狀態：不靠 --events 檔，直接建一個有帳號、但完全
    沒有事件的 AppState，驗證「接下來沒有行程」與月視圖無資料時不破版。"""
    manifest: list[str] = []
    settings = Settings()
    settings.ensure_account("empty@example.com").calendars["c"] = True
    state = AppState()
    state.set_events("empty@example.com", [], NOW)
    snap = state.snapshot()

    settings.view_span = "day"
    settings.view_mode = "agenda"
    surf = _surface()
    dashboard.render(surf, snap, settings, NOW)
    _save(surf, out_dir, "agenda-empty", manifest)

    settings.view_span = "month"
    settings.view_mode = "lanes"
    surf = _surface()
    dashboard.render(surf, snap, settings, NOW)
    _save(surf, out_dir, "month-empty", manifest)
    return manifest


def render_token_invalid(state: AppState, settings: Settings, out_dir: Path) -> list[str]:
    """帳號 token 失效狀態：設定頁該帳號卡片顯示實際錯誤訊息（st.error）。"""
    manifest: list[str] = []
    target = "kevin@interagent.io" if "kevin@interagent.io" in settings.accounts \
        else next(iter(settings.accounts), None)
    if target is not None:
        state.set_error(target, "帳號授權已失效，請重新登入", NOW)
    snap = state.snapshot()
    surf = _surface()
    settings_view.render(surf, snap, settings, None)
    _save(surf, out_dir, "settings_token_invalid", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path, help="事件快取 JSON（見 store.save_cache）")
    parser.add_argument("--out", required=True, type=Path, help="輸出 PNG 的資料夾")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    pygame.init()

    state, settings = load_state_and_settings(args.events)

    manifest: list[str] = []
    manifest += render_matrix(state, settings, args.out)
    manifest += render_settings_pages(state, settings, args.out)
    manifest += render_alarm_pages(args.out)
    manifest += render_detail_overlay(state, settings, args.out)
    manifest += render_alarm_firing(args.out)
    manifest += render_syncing(state, settings, args.out)
    manifest += render_token_invalid(state, settings, args.out)
    manifest += render_empty_states(args.out)

    print(f"共產出 {len(manifest)} 張 PNG：")
    for p in manifest:
        print(" ", p)

    pygame.quit()


if __name__ == "__main__":
    main()
