import pygame

from deskbar.ui import flipclock


def test_draw_all_phases_no_crash():
    surf = pygame.Surface((1920, 480))
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        flipclock.draw(surf, 40, 40, "14:38", "14:37", p)
    flipclock.draw(surf, 40, 40, "14:38", "14:38", 1.0)


def test_fold_height_eases_in_slower_than_linear():
    """前半段 ease-in：progress=0.25（線性應收到一半）時摺頁要還比一半高——
    起步慢、越壓越快才有重力感。"""
    half = 48
    assert flipclock._fold_h(0.0, half) == half
    assert flipclock._fold_h(0.25, half) > half // 2
    assert flipclock._fold_h(0.4999, half) <= 2
    heights = [flipclock._fold_h(p / 100, half) for p in range(0, 50, 5)]
    assert heights == sorted(heights, reverse=True), "摺頁高度應單調遞減"


def test_drop_height_eases_out_faster_than_linear():
    """後半段 ease-out：progress=0.75（線性應展開一半）時要已超過一半——
    快速甩下、落定前減速。"""
    half = 48
    assert flipclock._drop_h(0.5, half) == 1
    assert flipclock._drop_h(0.75, half) > half // 2
    assert flipclock._drop_h(1.0, half) == half
    heights = [flipclock._drop_h(0.5 + p / 100, half) for p in range(0, 51, 5)]
    assert heights == sorted(heights), "展開高度應單調遞增"


def test_shade_alpha_peaks_at_horizontal_and_vanishes_at_endpoints():
    assert flipclock._shade_alpha(0.0) == 0
    assert flipclock._shade_alpha(1.0) == 0
    assert flipclock._shade_alpha(0.5) == 120
    assert flipclock._shade_alpha(0.25) == 60


def test_mid_flip_frame_differs_from_settled_frame():
    a = pygame.Surface((1920, 480))
    b = pygame.Surface((1920, 480))
    flipclock.draw(a, 40, 40, "14:38", "14:37", 0.45)
    flipclock.draw(b, 40, 40, "14:38", "14:37", 1.0)
    assert pygame.image.tobytes(a, "RGB") != pygame.image.tobytes(b, "RGB")


def test_flap_shade_keeps_rounded_corners_clean():
    """審查抓到的圓角污漬回歸鎖：陰影若不夾到卡片自身 alpha，圓角外會多出
    半透明黑方角——淺色主題白卡上是一路往下掃的灰色方角污漬。翻牌中幀在
    「flap 圓角外、下層卡片內」的像素必須跟落定幀完全一致。"""
    from deskbar.ui import theme
    theme.set_theme("light")
    try:
        mid = pygame.Surface((400, 300))
        mid.fill(theme.C["bg"])
        flipclock.draw(mid, 40, 40, "8", "7", 0.25)
        settled = pygame.Surface((400, 300))
        settled.fill(theme.C["bg"])
        flipclock.draw(settled, 40, 40, "8", "8", 1.0)
        fh = flipclock._fold_h(0.25, 65)          # digit_h=130 → half=65
        probe = (41, 40 + 65 - fh + 1)            # 縮放後 flap 的左上圓角外
        assert mid.get_at(probe)[:3] == settled.get_at(probe)[:3], \
            "翻牌陰影不得在圓角外留下灰色方角"
    finally:
        theme.set_theme("dark")
