import pygame

from deskbar.ui import theme


def test_font_loads_headless():
    f = theme.font(20)
    surf = f.render("測試中文", True, (255, 255, 255))
    assert surf.get_width() > 0
