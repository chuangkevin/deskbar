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


def test_dev_window_to_logical_four_rotations():
    from deskbar.transform import dev_window_to_logical
    # 0°：直接等比映射（左上→左上、右下→右下）
    assert dev_window_to_logical(0, 0, 1152, 288, 0) == (0, 0)
    assert dev_window_to_logical(1151, 287, 1152, 288, 0) == (1919, 479)
    # 90°（視窗直立，邏輯順時針轉上去）：視窗左上＝邏輯左下
    assert dev_window_to_logical(0, 0, 288, 1152, 90) == (0, 479)
    assert dev_window_to_logical(287, 1151, 288, 1152, 90) == (1919, 0)
    # 180°：對角顛倒
    assert dev_window_to_logical(0, 0, 1152, 288, 180) == (1919, 479)
    # 270°：視窗左上＝邏輯右上
    assert dev_window_to_logical(0, 0, 288, 1152, 270) == (1919, 0)
    # 中心點在四種旋轉下都回到中心
    for r, (w, h) in [(0, (1152, 288)), (90, (288, 1152)), (180, (1152, 288)), (270, (288, 1152))]:
        x, y = dev_window_to_logical((w - 1) / 2, (h - 1) / 2, w, h, r)
        assert abs(x - 960) <= 1 and abs(y - 240) <= 1, (r, x, y)
