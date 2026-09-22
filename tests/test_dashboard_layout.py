"""三欄座標常數的守門測試：右欄兩欄化之後，中欄右界、右欄範圍、頂帶四顆鈕彼此不重疊。"""
from deskbar.ui import dashboard as d


def test_column_constants():
    assert d.TL_X1 == 1280
    assert d.USAGE_X0 == d.TL_X1 + 20
    assert d.USAGE_X0 + d.USAGE_W == 1900
    assert d.TL_AREA.x + d.TL_AREA.w == d.TL_X1


def test_topbar_buttons_inside_center_and_disjoint():
    btns = sorted([d.WORK_BTN, d.CENTER_BTN, d.SPAN_BTN, d.MODE_BTN], key=lambda r: r.x)
    for r in btns:
        assert r.x >= d.TL_X0 and r.x + r.w <= d.TL_X1
    for a, b in zip(btns, btns[1:]):
        assert a.x + a.w <= b.x
