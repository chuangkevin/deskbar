import pygame

from deskbar.ui import theme


def test_font_loads_headless():
    f = theme.font(20)
    surf = f.render("測試中文", True, (255, 255, 255))
    assert surf.get_width() > 0
    # 偵測方格（tofu）：若字型缺 CJK glyph，SDL_ttf 會對所有缺字字元畫同一個
    # .notdef 替補字形，導致「中」與保證任何字型都沒有的 noncharacter U+FFFF
    # 畫出一模一樣的像素。有 CJK glyph 的字型兩者會不同。
    # （metrics() 在本機 SDL_ttf 版本不會回傳 None，故不用 metrics 判斷。）
    zh = pygame.image.tostring(f.render("中", True, (255, 255, 255)), "RGBA")
    tofu = pygame.image.tostring(f.render("￿", True, (255, 255, 255)), "RGBA")
    assert zh != tofu
