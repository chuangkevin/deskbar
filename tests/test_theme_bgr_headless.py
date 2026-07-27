"""BGR 色板開關：DESKBAR_BGR=1 時 set_theme() 套用當下主題就把 C／ACCOUNT_COLORS
全部 (r,g,b)→(b,g,r)；沒設就完全不動——這支測試把「dev 模式零行為差異」與
「開關真的有交換」兩件事都釘死，避免未來改壞。

2026-07-27 高對比深色改版：舊版 now=(240,153,123)／now_text=(74,27,12)／
teal 主色=(93,202,165)／bg=(15,15,15)／text=(236,236,236) 全面換成高對比新值
（見 deskbar/ui/theme.py 的 PALETTES["dark"]），這裡的字面值跟著更新，
「BGR 開關本身邏輯正確」這件事的驗證方式不變。"""
import importlib

from deskbar.ui import theme


def test_bgr_disabled_by_default_matches_literal_values():
    assert theme.C["now"] == (255, 138, 101)
    assert theme.C["now_text"] == (60, 20, 8)
    assert theme.ACCOUNT_COLORS[0][0] == (0, 228, 180)
    assert theme.col((10, 20, 30)) == (10, 20, 30)


def test_col_helper_is_identity_when_flag_off():
    # 灰階對稱色 (r==g==b) 換或不換視覺上沒差，但函式邏輯本身仍應正確跳過。
    assert theme.col((15, 15, 15)) == (15, 15, 15)
    assert theme.col((236, 236, 236)) == (236, 236, 236)


def test_bgr_env_swaps_channels_on_module_load(monkeypatch):
    monkeypatch.setenv("DESKBAR_BGR", "1")
    try:
        importlib.reload(theme)
        assert theme.C["now"] == (101, 138, 255)
        assert theme.C["now_text"] == (8, 20, 60)
        assert theme.ACCOUNT_COLORS[0][0] == (180, 228, 0)
        assert theme.col((10, 20, 30)) == (30, 20, 10)
        # 灰階對稱色交換前後不變。
        assert theme.C["bg"] == (0, 0, 0)
        assert theme.C["text"] == (255, 255, 255)
    finally:
        monkeypatch.delenv("DESKBAR_BGR", raising=False)
        importlib.reload(theme)   # 還原成非 BGR 狀態，避免污染其他測試模組


def test_reload_without_env_restores_original_state(monkeypatch):
    monkeypatch.setenv("DESKBAR_BGR", "1")
    importlib.reload(theme)
    monkeypatch.delenv("DESKBAR_BGR")
    importlib.reload(theme)
    assert theme.C["now"] == (255, 138, 101)
    assert theme.ACCOUNT_COLORS[0][0] == (0, 228, 180)
