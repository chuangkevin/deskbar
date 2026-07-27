"""deskbar.ui.weatherfx（HTC Sense 場景版）契約測試：各場景有畫東西且會動、
純函式可重現、未知 code 不畫、粒子不越界、日夜切換有差、雷雨閃電週期、
puff 快取單槽不長大＋主題切換清空。"""
from __future__ import annotations

import pygame
import pytest

from deskbar.ui import theme, weatherfx

W, H = 400, 480


def _surf(w: int = 1920, h: int = 480) -> "pygame.Surface":
    s = pygame.Surface((w, h))
    s.fill(theme.C["bg"])
    return s


def _draw(code: int, t: float, night: bool = False, x0: int = 0) -> "pygame.Surface":
    s = _surf()
    weatherfx.draw(s, code, t, x0=x0, w=W, h=H, night=night)
    return s


def _panel_bytes(s: "pygame.Surface", x0: int = 0) -> bytes:
    return pygame.image.tobytes(s.subsurface(pygame.Rect(x0, 0, W, H)), "RGB")


# ---------------------------------------------------------------- code 分族

def test_code_families_cover_expected_ranges():
    assert 0 in weatherfx.CLEAR_CODES
    for c in (1, 2, 3):
        assert c in weatherfx.CLOUD_CODES
    for c in (45, 48):
        assert c in weatherfx.FOG_CODES
    for c in (51, 61, 67, 80, 82):
        assert c in weatherfx.RAIN_CODES
    for c in (71, 77, 85, 86):
        assert c in weatherfx.SNOW_CODES
    for c in (95, 99):
        assert c in weatherfx.THUNDER_CODES
    for c in (0, 2, 45, 61, 73, 95):
        assert c in weatherfx.ANIMATED_CODES
    assert 100 not in weatherfx.ANIMATED_CODES


# ---------------------------------------------------------------- 有畫、會動、可重現

_FAMILIES = [(0, False), (0, True), (1, False), (2, False), (3, False),
             (45, False), (51, False), (61, False), (82, False), (73, False),
             (95, False)]


@pytest.mark.parametrize("code,night", _FAMILIES)
def test_every_family_draws_ink(code, night):
    assert _panel_bytes(_draw(code, 1.0, night)) != _panel_bytes(_surf()), \
        f"code {code} night={night} 應該畫出場景"


@pytest.mark.parametrize("code,night", _FAMILIES)
def test_every_family_animates_between_time_samples(code, night):
    a = _panel_bytes(_draw(code, 1.0, night))
    b = _panel_bytes(_draw(code, 1.7, night))
    assert a != b, f"code {code} night={night} 在 t=1.0 與 t=1.7 應該畫出不同幀"


@pytest.mark.parametrize("code,night", _FAMILIES)
def test_same_inputs_render_identical_frames(code, night):
    assert _panel_bytes(_draw(code, 2.345, night)) == \
        _panel_bytes(_draw(code, 2.345, night)), "純函式：同參數必須逐像素相同"


def test_unknown_code_draws_nothing():
    assert _panel_bytes(_draw(100, 3.0)) == _panel_bytes(_surf())


# ---------------------------------------------------------------- 不越界

@pytest.mark.parametrize("code,night", [(0, False), (0, True), (3, False),
                                        (82, False), (95, False), (73, False),
                                        (45, False)])
def test_never_draws_outside_panel_rect(code, night):
    s = _surf()
    x0 = 200
    # 多個 t 取樣：雲/雨/雪的進出場、閃電 strobe 都掃到
    for t in (0.0, 0.5, 1.3, 2.9, weatherfx.FLASH_PERIOD_S + 0.05):
        weatherfx.draw(s, code, t, x0=x0, w=W, h=H, night=night)
    bg = theme.C["bg"]
    for y in range(0, 480, 4):
        for x in list(range(0, x0, 5)) + list(range(x0 + W, 1920, 5)):
            assert s.get_at((x, y))[:3] == bg, f"({x},{y}) 畫出了面板矩形之外"


def test_zero_or_negative_size_is_noop():
    s = _surf()
    weatherfx.draw(s, 61, 1.0, w=0, h=480)
    weatherfx.draw(s, 61, 1.0, w=400, h=0)
    assert _panel_bytes(s) == _panel_bytes(_surf())


# ---------------------------------------------------------------- 日夜切換

def test_clear_day_and_night_render_different_scenes():
    assert _panel_bytes(_draw(0, 1.0, night=False)) != \
        _panel_bytes(_draw(0, 1.0, night=True)), "晴天白天=太陽、夜間=月亮星空"


def test_night_stars_twinkle_over_time():
    assert _panel_bytes(_draw(0, 1.0, night=True)) != \
        _panel_bytes(_draw(0, 1.4, night=True))


# ---------------------------------------------------------------- 雷雨閃電

def test_thunder_flash_lights_whole_panel_on_strobe_frame():
    bg = theme.C["bg"]

    def nonbg_grid_count(surf):
        return sum(1 for y in range(10, H, 48) for x in range(10, W, 40)
                   if surf.get_at((x, y))[:3] != bg)

    flash = nonbg_grid_count(_draw(95, weatherfx.FLASH_PERIOD_S * 2 + 0.05))
    normal = nonbg_grid_count(_draw(95, weatherfx.FLASH_PERIOD_S * 2 + 3.0))
    total = len(range(10, H, 48)) * len(range(10, W, 40))
    assert flash == total, "strobe 幀整片白幕應覆蓋所有取樣點"
    assert normal < total, "非 strobe 幀只有雨絲，不該整片都非背景色"


# ---------------------------------------------------------------- 玻璃前景層


def _draw_glass(code: int, t: float, x0: int = 0) -> "pygame.Surface":
    s = _surf()
    weatherfx.draw_glass(s, code, t, x0=x0, w=W, h=H)
    return s


def test_glass_layer_only_for_rain_thunder_snow():
    for code in (61, 82, 95, 73):
        assert code in weatherfx.GLASS_CODES
    for code in (0, 2, 45, 100):
        assert _panel_bytes(_draw_glass(code, 9.0)) == _panel_bytes(_surf()), \
            f"code {code} 不該有玻璃層"


def test_glass_rain_drops_accumulate_then_wiper_clears():
    tc_full = 9.5                      # 積聚末期：水滴最多
    tc_clean = weatherfx._WIPE_START + 2 * weatherfx._WIPE_SWEEP_S + 0.5   # 刷完
    full = _panel_bytes(_draw_glass(61, tc_full))
    clean = _panel_bytes(_draw_glass(61, tc_clean))
    assert full != _panel_bytes(_surf()), "積聚期玻璃上應該有水滴"
    assert clean == _panel_bytes(_surf()), "雨刷去回掃完之後玻璃應該是乾淨的"


def test_glass_wiper_arm_visible_during_sweep():
    sweep = _panel_bytes(_draw_glass(61, weatherfx._WIPE_START + 0.6))
    assert sweep != _panel_bytes(_surf())
    # 掃動中幀與積聚幀不同（有臂、有部分水滴已被抹掉）
    assert sweep != _panel_bytes(_draw_glass(61, 9.5))


def test_glass_rain_cycle_repeats_deterministically():
    a = _panel_bytes(_draw_glass(61, 3.3))
    b = _panel_bytes(_draw_glass(61, 3.3 + weatherfx.WIPE_PERIOD_S))
    assert a == b, "玻璃層以 WIPE_PERIOD_S 為週期，跨週期同相位必須逐像素相同"


def test_glass_snow_flakes_stick_and_melt():
    a = _panel_bytes(_draw_glass(73, 2.0))
    b = _panel_bytes(_draw_glass(73, 4.5))
    assert a != _panel_bytes(_surf()), "雪天玻璃上應該有黏附的雪花"
    assert a != b, "雪花淡入/漸融，不同時刻幀不同"


def test_glass_layer_never_draws_outside_panel_rect():
    s = _surf()
    x0 = 200
    for t in (2.0, 9.5, weatherfx._WIPE_START + 0.6, weatherfx._WIPE_START + 1.8):
        weatherfx.draw_glass(s, 61, t, x0=x0, w=W, h=H)
        weatherfx.draw_glass(s, 73, t, x0=x0, w=W, h=H)
    bg = theme.C["bg"]
    for y in range(0, 480, 4):
        for x in list(range(0, x0, 5)) + list(range(x0 + W, 1920, 5)):
            assert s.get_at((x, y))[:3] == bg, f"玻璃層 ({x},{y}) 畫出面板矩形之外"


# ---------------------------------------------------------------- puff 快取

def test_cloud_puff_cache_is_bounded_and_reused():
    weatherfx._clear_cache()
    weatherfx.build_count = 0
    for t in (0.0, 0.5, 1.0, 7.7, 42.0):
        _draw(3, t)
    assert weatherfx.build_count <= 2, "puff 只有兩種尺寸，同 code 重複畫不得重建"
    assert len(weatherfx._sprites) <= 2
    # 固定 key 組合（2 尺寸 × 2 alpha × 主題）：無論畫多少幀，容器物理上不會長大
    for t in range(50):
        _draw(2, float(t))
    assert len(weatherfx._sprites) <= 4
    assert weatherfx.build_count <= 4


def test_cloud_opacity_independent_of_draw_order():
    """審查抓到的快取污染回歸鎖：key 少了 alpha 時，「開機後誰先畫」會決定
    所有雲的厚度（code 2 先畫過之後，code 3 的幀逐位元等於 code 2 的透明度），
    破壞純函式契約、也讓驗證工具出的圖跟實機不一致。"""
    weatherfx._clear_cache()
    fresh = _panel_bytes(_draw(3, 1.0))
    weatherfx._clear_cache()
    _draw(2, 1.0)                    # 先畫多雲，讓 puff 快取先被 alpha=66 佔據
    polluted = _panel_bytes(_draw(3, 1.0))
    assert fresh == polluted, "陰天雲厚度不得取決於繪製順序（快取 key 必須含 alpha）"


def test_ambient_fps_tiers_by_scene_speed():
    for code in (51, 61, 82, 95, 99):
        assert weatherfx.ambient_fps(code) == 15, "雨/雷是快場景"
    for code in (71, 73, 86):
        assert weatherfx.ambient_fps(code) == 12
    for code in (0, 1, 2, 3, 45, 48):
        assert weatherfx.ambient_fps(code) == 8, "晴/雲/霧是慢場景，8fps 肉眼無感"


def test_theme_switch_clears_puff_cache_and_recolors():
    weatherfx._clear_cache()
    weatherfx.build_count = 0
    _draw(3, 1.0)
    built_dark = weatherfx.build_count
    assert built_dark >= 1
    try:
        theme.set_theme("light")
        assert len(weatherfx._sprites) == 0, "主題切換應清空 puff 快取"
        _draw(3, 1.0)
        assert weatherfx.build_count > built_dark, "新主題下應以新配色重建"
    finally:
        theme.set_theme("dark")
