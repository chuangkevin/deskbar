import pygame

from deskbar.ui import flipclock


def test_draw_all_phases_no_crash():
    surf = pygame.Surface((1920, 480))
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        flipclock.draw(surf, 40, 40, "14:38", "14:37", p)
    flipclock.draw(surf, 40, 40, "14:38", "14:38", 1.0)
