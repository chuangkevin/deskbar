import pygame

from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import icons, qr, settings_view


def test_draw_gear_no_crash():
    surf = pygame.Surface((1920, 480))
    surf.fill((15, 15, 15))
    color = (111, 111, 111)
    icons.draw_gear(surf, 432, 432, 20, color)
    region = pygame.Rect(396, 396, 72, 72)
    hit = False
    for px in range(region.x, region.x + region.w):
        for py in range(region.y, region.y + region.h):
            if surf.get_at((px, py))[:3] == color:
                hit = True
                break
        if hit:
            break
    assert hit, "齒輪區域內找不到指定顏色的像素，代表沒有真的畫出東西"


def test_qr_matrix_renders():
    surf = pygame.Surface((1920, 480))
    surf.fill((15, 15, 15))
    x, y, size = 100, 50, 200
    text = "https://desk.sisihome.org/test-qr"

    before = qr.build_count
    qr.draw_qr(surf, x, y, size, text)
    after_first = qr.build_count
    assert after_first == before + 1

    region = pygame.Rect(x, y, size, size)
    seen_black = False
    seen_white = False
    for px in range(region.x, region.x + region.w):
        for py in range(region.y, region.y + region.h):
            c = surf.get_at((px, py))[:3]
            if c == (0, 0, 0):
                seen_black = True
            elif c == (255, 255, 255):
                seen_white = True
        if seen_black and seen_white:
            break
    assert seen_black and seen_white, "QR 區域內應同時存在黑與白像素"

    # 相同 (text, size) 第二次呼叫應命中快取，不再重新計算。
    qr.draw_qr(surf, x, y, size, text)
    assert qr.build_count == after_first


def test_settings_has_qr_and_actions():
    surf = pygame.Surface((1920, 480))
    settings = Settings()
    settings.ensure_account("a@x.com").calendars["c1"] = True
    hits = settings_view.render(surf, AppState().snapshot(), settings, None)
    actions = {h.action for h in hits}
    assert "rotate" in actions
    assert "settings_done" in actions
