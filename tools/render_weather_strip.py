"""天氣場景動畫驗證：每個場景（晴日/晴夜/多雲/陰/霧/雨/大雨/雷雨/雪）沿時間軸
取 6 幀左欄畫面拼成 filmstrip PNG，供人眼核對「有沒有動、動得像不像樣」——比照
render_matrix 的鐵則：任何動畫改動先出圖看過才部署。

走的就是實機的氛圍幀路徑（dashboard.render_panel_only），日夜判定、主題、BGR
都跟上線行為一致；固定 NOW 與 t 序列，輸出可重現、可 diff。

用法：
    .venv/bin/python tools/render_weather_strip.py --out /tmp/weather_strips
    .venv/bin/python tools/render_weather_strip.py --out /tmp/weather_strips --theme both
    .venv/bin/python tools/render_weather_strip.py --out /tmp/weather_strips --gif

--gif 需要 Pillow（純開發工具依賴，Pi 上不需要）：每場景另出一張 15fps 動圖，
雷雨場景時間窗刻意涵蓋 FLASH_PERIOD_S，讓閃電一定入鏡。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from deskbar.config import Settings  # noqa: E402
from deskbar.store import AppState  # noqa: E402
from deskbar.ui import dashboard, theme  # noqa: E402
from deskbar.ui.weatherfx import FLASH_PERIOD_S  # noqa: E402
from deskbar.weather import Weather  # noqa: E402

TZ = ZoneInfo("Asia/Taipei")
DAY = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)     # 白天場景的固定「現在」
NIGHT = datetime(2026, 7, 27, 22, 0, tzinfo=TZ)   # 夜間場景（>=19 點觸發月亮星空）
PANEL = pygame.Rect(0, 0, dashboard.PANEL_W, 480)

# (檔名, code, now, t0)；t0 讓雷雨的取樣窗涵蓋閃電 strobe、雨的取樣窗涵蓋
# 「水滴積聚→雨刷掃動」（WIPE_PERIOD_S=14 循環的 8.0 起跳：8.0~9.2 積滿、
# 10.4/11.6 落在去程/回程掃動中）。
SCENARIOS = [
    ("clear_day", 0, DAY, 0.0),
    ("clear_night", 0, NIGHT, 0.0),
    ("partly_cloudy", 1, DAY, 0.0),
    ("overcast", 3, DAY, 0.0),
    ("fog", 45, DAY, 0.0),
    ("rain", 61, DAY, 8.0),
    ("heavy_rain", 82, DAY, 8.0),
    ("thunder", 95, DAY, FLASH_PERIOD_S - 0.3),
    ("snow", 73, DAY, 0.0),
]
STRIP_STEPS = [0.0, 0.3, 0.6, 1.2, 2.4, 3.6]      # filmstrip 的 6 個取樣點（秒）
_LONG_GIF = {"thunder", "rain", "heavy_rain"}      # 這幾景 8 秒才裝得下完整循環


def _fixture(code: int) -> tuple[AppState, Settings]:
    state = AppState()
    state.set_weather(Weather(temp=31.0, code=code, tmax=33.0, tmin=27.0,
                              label="南港", fetched_at=DAY))
    return state, Settings()


def _panel_frame(state: AppState, settings: Settings, now: datetime,
                 t: float) -> "pygame.Surface":
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    dashboard.render_panel_only(surf, state.snapshot(), settings, now, t)
    return surf.subsurface(PANEL).copy()

def render_strip(name: str, code: int, now: datetime, t0: float,
                 out_dir: Path) -> Path:
    state, settings = _fixture(code)
    gap = 4
    strip = pygame.Surface((PANEL.w * len(STRIP_STEPS) + gap * (len(STRIP_STEPS) - 1),
                            PANEL.h))
    strip.fill(theme.C["panel_line"])
    for i, dt in enumerate(STRIP_STEPS):
        strip.blit(_panel_frame(state, settings, now, t0 + dt),
                   (i * (PANEL.w + gap), 0))
    path = out_dir / f"strip_{name}.png"
    pygame.image.save(strip, str(path))
    return path


def render_gif(name: str, code: int, now: datetime, t0: float, out_dir: Path,
               seconds: float = 4.0, fps: int = 15) -> Path:
    from PIL import Image   # 純開發工具依賴：沒裝就讓 --gif 直接報錯，不影響 strip
    state, settings = _fixture(code)
    frames = []
    for k in range(int(seconds * fps)):
        surf = _panel_frame(state, settings, now, t0 + k / fps)
        raw = pygame.image.tobytes(surf, "RGB")
        frames.append(Image.frombytes("RGB", (PANEL.w, PANEL.h), raw))
    path = out_dir / f"anim_{name}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=round(1000 / fps), loop=0)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("/tmp/weather_strips"))
    ap.add_argument("--theme", choices=["dark", "light", "both"], default="dark")
    ap.add_argument("--gif", action="store_true")
    args = ap.parse_args()
    pygame.init()
    args.out.mkdir(parents=True, exist_ok=True)
    themes = ["dark", "light"] if args.theme == "both" else [args.theme]
    for theme_name in themes:
        theme.set_theme(theme_name)
        suffix = "" if theme_name == "dark" else "_light"
        for name, code, now, t0 in SCENARIOS:
            p = render_strip(f"{name}{suffix}", code, now, t0, args.out)
            print(p)
            if args.gif:
                gif_t0 = 6.0 if name in ("rain", "heavy_rain") else t0
                print(render_gif(f"{name}{suffix}", code, now, gif_t0, args.out,
                                 seconds=8.0 if name in _LONG_GIF else 4.0))
    theme.set_theme("dark")


if __name__ == "__main__":
    main()
