from deskbar.layout import Rect


def test_rect_contains():
    r = Rect(10, 10, 100, 50)
    assert r.contains(10, 10)
    assert r.contains(109.9, 59.9)
    assert not r.contains(110, 10)
    assert not r.contains(9, 10)
