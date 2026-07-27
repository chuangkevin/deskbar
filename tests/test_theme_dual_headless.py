"""雙主題色板核心行為（deskbar.ui.theme）：
- dark/light 兩套 PALETTES key 完全一致，不會有主題切過去缺 key 悄悄 KeyError。
- set_theme() 真的會換 C／ACCOUNT_COLORS 的值、換 current_theme()、
  並呼叫所有已登記的快取清除 callback。
- BGR 開關（DESKBAR_BGR=1）在 light 主題下依然正確套用 R/B 交換。

每支會呼叫 set_theme("light") 的測試都用 try/finally 换回 "dark"，避免污染
同一個 pytest session 裡其他假設「預設就是 dark」的測試（例如
test_transitions_headless.py 的開機 splash 黑底斷言）。
"""
from __future__ import annotations

import importlib

from deskbar.ui import theme


def test_palettes_have_identical_keys():
    dark_keys = set(theme.PALETTES["dark"])
    light_keys = set(theme.PALETTES["light"])
    assert dark_keys, "palette 不該是空字典"
    assert dark_keys == light_keys


def test_account_palettes_have_same_length_both_themes():
    from deskbar.ui.theme import _ACCOUNTS_RAW
    assert len(_ACCOUNTS_RAW["dark"]) == len(_ACCOUNTS_RAW["light"]) == 4


def test_default_theme_on_import_is_dark():
    assert theme.current_theme() == "dark"
    assert theme.C["bg"] == theme.PALETTES["dark"]["bg"]


def test_set_theme_switches_c_values_and_current_theme():
    try:
        dark_bg = theme.C["bg"]
        theme.set_theme("light")
        assert theme.current_theme() == "light"
        assert theme.C["bg"] == theme.PALETTES["light"]["bg"]
        assert theme.C["bg"] != dark_bg
        # 全部 key 都要換過去，不能只換一部分。
        for key, value in theme.PALETTES["light"].items():
            assert theme.C[key] == value
    finally:
        theme.set_theme("dark")


def test_set_theme_unknown_name_silently_falls_back_to_dark():
    try:
        theme.set_theme("light")
        theme.set_theme("not-a-real-theme")
        assert theme.current_theme() == "dark"
        assert theme.C["bg"] == theme.PALETTES["dark"]["bg"]
    finally:
        theme.set_theme("dark")


def test_account_colors_switch_with_theme_and_keep_shape():
    try:
        dark_first = theme.ACCOUNT_COLORS[0]
        theme.set_theme("light")
        light_first = theme.ACCOUNT_COLORS[0]
        assert len(theme.ACCOUNT_COLORS) == 4
        assert dark_first != light_first
        for main, fill in theme.ACCOUNT_COLORS:
            assert len(main) == 3 and len(fill) == 3
    finally:
        theme.set_theme("dark")


def test_set_theme_calls_registered_cache_clear_callbacks():
    calls = []
    theme.register_cache_clear(lambda: calls.append("cleared"))
    try:
        theme.set_theme("light")
        assert calls == ["cleared"]
        theme.set_theme("dark")
        assert calls == ["cleared", "cleared"]
    finally:
        theme.set_theme("dark")


def test_flipclock_cache_actually_clears_on_theme_switch():
    """比 callback 有沒有被呼叫更進一步：真的畫一張翻牌卡，切主題後確認
    快取字典被清空（不是還留著舊主題烤好的 Surface）。"""
    from deskbar.ui import flipclock
    try:
        flipclock._cache.clear()
        pygame_surf = __import__("pygame").Surface((200, 200))
        flipclock.draw(pygame_surf, 0, 0, "12", "12", 1.0, digit_h=60)
        assert flipclock._cache, "應該已經烤出至少一張數字卡快取"
        theme.set_theme("light")
        assert flipclock._cache == {}, "切主題後應清空數字卡快取"
    finally:
        theme.set_theme("dark")
        flipclock._cache.clear()


def test_bgr_applies_correctly_under_light_theme(monkeypatch):
    monkeypatch.setenv("DESKBAR_BGR", "1")
    try:
        importlib.reload(theme)
        theme.set_theme("light")
        r, g, b = theme.PALETTES["light"]["now"]
        assert theme.C["now"] == (b, g, r)
        # 灰階對稱色（light bg 不對稱，這裡挑 warn 之外真正對稱的 gray-ish 值驗證
        # col() 邏輯本身，不是驗證某個 key 剛好對稱）。
        assert theme.col((11, 22, 33)) == (33, 22, 11)
    finally:
        monkeypatch.delenv("DESKBAR_BGR", raising=False)
        importlib.reload(theme)   # 還原成非 BGR、預設 dark 狀態，避免污染其他測試
