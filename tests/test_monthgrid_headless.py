"""月視圖窗口外日期數字對比度：改走 theme.C["date_dim"]（兩主題各自定義，見
deskbar/ui/theme.py），且仍要跟窗口內的 theme.C["text2"] 拉出可辨識的明暗差。

2026-07-27 雙主題重構：舊版模組級常量 OUT_OF_WINDOW_DATE_COLOR=(130,130,130)
拆成主題 key，monthgrid.py 已不再輸出該常量，這裡改直接讀 theme.C["date_dim"]。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.config import Settings
from deskbar.layout import Rect
from deskbar.ui import monthgrid, theme

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=TZ)   # 資料窗口 [7/20, 8/26]；7/1 明確在窗口外
OUT_OF_WINDOW_DAY = date(2026, 7, 1)
AREA = Rect(500, 52, 1400, 368)


def _settings():
    s = Settings()
    s.ensure_account("a@x.com").calendars["c"] = True
    return s


def test_out_of_window_date_color_is_distinct_theme_key():
    assert theme.C["date_dim"] != theme.C["muted"]


def test_out_of_window_day_has_no_goto_day_hit():
    settings = _settings()
    win_start = NOW.replace(day=1)
    hits = monthgrid.render_month(pygame.Surface((1920, 480)), [], ["a@x.com"], settings,
                                  win_start, AREA, NOW)
    assert not any(h.action == "goto_day" and h.data == OUT_OF_WINDOW_DAY for h in hits)
    assert any(h.action == "goto_day" and h.data == NOW.date() for h in hits)


def test_out_of_window_day_header_uses_date_dim_color():
    """量測 7/1（確定窗口外）表頭數字像素的最亮值，應貼近 theme.C["date_dim"]
    而不是 theme.C["muted"]——挑最亮像素避開反鋸齒邊緣造成的誤判。"""
    settings = _settings()
    win_start = NOW.replace(day=1)
    surf = pygame.Surface((1920, 480))
    monthgrid.render_month(surf, [], ["a@x.com"], settings, win_start, AREA, NOW)

    days_in_month = 31   # 2026-07
    col_w = (AREA.w - monthgrid.LANE_LABEL_W) / days_in_month
    d = OUT_OF_WINDOW_DAY.day
    cx = AREA.x + monthgrid.LANE_LABEL_W + (d - 1) * col_w + col_w / 2

    best = (0, 0, 0)
    for y in range(int(AREA.y) + 2, int(AREA.y) + 22):
        for x in range(int(cx) - 12, int(cx) + 12):
            px = surf.get_at((x, y))[:3]
            if sum(px) > sum(best):
                best = px
    assert best == theme.C["date_dim"]
