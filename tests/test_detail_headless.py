from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.layout import Rect
from deskbar.models import Event
from deskbar.ui import detail, theme
from deskbar.ui.dashboard import PANEL_W, TL_X0, TL_X1

TZ = ZoneInfo("Asia/Taipei")


def test_detail_hits_order():
    surf = pygame.Surface((1920, 480))
    tz = ZoneInfo("Asia/Taipei")
    e = Event("e", "a@x.com", "c", "看牙", datetime(2026, 7, 27, 14, tzinfo=tz),
              datetime(2026, 7, 27, 15, tzinfo=tz), False, "診所", None)
    hits = detail.render(surf, e)
    assert hits[0].action == "close" and hits[-1].action == "noop"
    # 卡片區域點擊應命中 noop（上層優先 = list 尾端優先）
    assert hits[-1].rect.contains(960, 240)


def _card_rect(hits) -> Rect:
    return hits[-1].rect


def test_detail_card_does_not_overlap_left_panel():
    """卡片必須完全落在時間軸區（x=500 起）內，不能蓋到左面板（PANEL_W=480）；
    右緣也不該超出時間軸右界（TL_X1=1900）。"""
    surf = pygame.Surface((1920, 480))
    e = Event("e", "a@x.com", "c", "看牙", datetime(2026, 7, 27, 14, tzinfo=TZ),
              datetime(2026, 7, 27, 15, tzinfo=TZ), False, "診所", None)
    hits = detail.render(surf, e)
    card = _card_rect(hits)
    assert card.x >= TL_X0 > PANEL_W
    assert card.x + card.w <= TL_X1


def test_allday_list_card_does_not_overlap_left_panel():
    surf = pygame.Surface((1920, 480))
    events = [Event("e", "a@x.com", "c", "整日事件",
                    datetime(2026, 7, 27, tzinfo=TZ),
                    datetime(2026, 7, 28, tzinfo=TZ), True, None, None)]
    hits = detail.render_allday_list(surf, events)
    card = _card_rect(hits)
    assert card.x >= TL_X0 > PANEL_W
    assert card.x + card.w <= TL_X1


def test_long_description_wraps_to_at_most_two_lines_with_ellipsis():
    """描述最多畫 2 行（量測式換行），放不下的內容以「…」結尾——直接驗證
    detail.py 實際會用的參數餵給 theme.wrap_lines，跟 render() 內部邏輯一致。"""
    long_desc = "很長的描述內容" * 40
    lines = theme.wrap_lines(long_desc, theme.font(22), detail.TEXT_MAX_W, 2)
    assert len(lines) <= 2
    assert lines[-1].endswith("…")
    for line in lines:
        assert theme.font(22).size(line)[0] <= detail.TEXT_MAX_W


def test_detail_render_with_long_description_does_not_crash():
    surf = pygame.Surface((1920, 480))
    e = Event("e", "a@x.com", "c", "看牙",
              datetime(2026, 7, 27, 14, tzinfo=TZ), datetime(2026, 7, 27, 15, tzinfo=TZ),
              False, "診所", "很長的描述內容" * 40)
    hits = detail.render(surf, e)
    assert hits[0].action == "close"
