from deskbar.transform import touch_to_logical, pygame_rotation_angle


def test_pygame_angles():
    assert pygame_rotation_angle(90) == -90
    assert pygame_rotation_angle(270) == 90


def test_touch_rotation_90_corners():
    # 順時針：邏輯(0,0) 在面板右上 → 面板右上角觸控應回到邏輯左上
    assert touch_to_logical(1.0, 0.0, 90) == (0, 0)
    # 面板左上 = 邏輯(0, 479)
    assert touch_to_logical(0.0, 0.0, 90) == (0, 479)
    # 面板右下 = 邏輯(1919, 0)
    assert touch_to_logical(1.0, 1.0, 90) == (1919, 0)


def test_touch_rotation_270_corners():
    assert touch_to_logical(0.0, 1.0, 270) == (0, 0)
    assert touch_to_logical(0.0, 0.0, 270) == (1919, 0)
    assert touch_to_logical(1.0, 1.0, 270) == (0, 479)


def test_center_maps_to_center():
    x, y = touch_to_logical(0.5, 0.5, 90)
    assert abs(x - 960) <= 1 and abs(y - 240) <= 1
