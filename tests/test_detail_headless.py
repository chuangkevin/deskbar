import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pygame

from deskbar.models import Event
from deskbar.ui import detail


def test_detail_hits_order():
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    surf = pygame.Surface((1920, 480))
    tz = ZoneInfo("Asia/Taipei")
    e = Event("e", "a@x.com", "c", "看牙", datetime(2026, 7, 27, 14, tzinfo=tz),
              datetime(2026, 7, 27, 15, tzinfo=tz), False, "診所", None)
    hits = detail.render(surf, e)
    assert hits[0].action == "close" and hits[-1].action == "noop"
    # 卡片區域點擊應命中 noop（上層優先 = list 尾端優先）
    assert hits[-1].rect.contains(960, 240)
    pygame.quit()
