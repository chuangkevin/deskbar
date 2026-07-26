"""BGR 色板開關：DESKBAR_BGR=1 時 theme 載入即把 C／ACCOUNT_COLORS 全部
(r,g,b)→(b,g,r)；沒設就完全不動——這支測試把「dev 模式零行為差異」與
「開關真的有交換」兩件事都釘死，避免未來改壞。"""
import importlib

from deskbar.ui import theme


def test_bgr_disabled_by_default_matches_literal_values():
    assert theme.C["now"] == (240, 153, 123)
    assert theme.C["now_text"] == (74, 27, 12)
    assert theme.ACCOUNT_COLORS[0][0] == (93, 202, 165)
    assert theme.col((10, 20, 30)) == (10, 20, 30)


def test_col_helper_is_identity_when_flag_off():
    # 灰階對稱色 (r==g==b) 換或不換視覺上沒差，但函式邏輯本身仍應正確跳過。
    assert theme.col((15, 15, 15)) == (15, 15, 15)
    assert theme.col((236, 236, 236)) == (236, 236, 236)


def test_bgr_env_swaps_channels_on_module_load(monkeypatch):
    monkeypatch.setenv("DESKBAR_BGR", "1")
    try:
        importlib.reload(theme)
        assert theme.C["now"] == (123, 153, 240)
        assert theme.C["now_text"] == (12, 27, 74)
        assert theme.ACCOUNT_COLORS[0][0] == (165, 202, 93)
        assert theme.col((10, 20, 30)) == (30, 20, 10)
        # 灰階對稱色交換前後不變。
        assert theme.C["bg"] == (15, 15, 15)
        assert theme.C["text"] == (236, 236, 236)
    finally:
        monkeypatch.delenv("DESKBAR_BGR", raising=False)
        importlib.reload(theme)   # 還原成非 BGR 狀態，避免污染其他測試模組


def test_reload_without_env_restores_original_state(monkeypatch):
    monkeypatch.setenv("DESKBAR_BGR", "1")
    importlib.reload(theme)
    monkeypatch.delenv("DESKBAR_BGR")
    importlib.reload(theme)
    assert theme.C["now"] == (240, 153, 123)
    assert theme.ACCOUNT_COLORS[0][0] == (93, 202, 165)
