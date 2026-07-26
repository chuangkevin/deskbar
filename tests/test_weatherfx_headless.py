"""deskbar.ui.weatherfx 契約測試：三態不炸、粒子不越界、未知 code 不畫、
快取不會無界成長（單一 slot，換 key 就整張覆蓋掉）。"""
import pygame

from deskbar.ui import weatherfx

BG = (5, 5, 5)


def _blank(w, h):
    surf = pygame.Surface((w, h))
    surf.fill(BG)
    return surf


def test_wmo_code_grouping_matches_contract():
    # 雨：51-67, 80-82, 95-99
    for code in (51, 60, 67, 80, 82, 95, 99):
        assert code in weatherfx.RAIN_CODES
    # 雲：1-3, 45, 48
    for code in (1, 2, 3, 45, 48):
        assert code in weatherfx.CLOUD_CODES
    # 晴：0
    assert 0 in weatherfx.CLEAR_CODES
    # 邊界外／未定義代碼不屬於任何一組
    for code in (4, 44, 46, 50, 68, 79, 83, 94, 100, -1, 999):
        assert code not in weatherfx.RAIN_CODES
        assert code not in weatherfx.CLOUD_CODES
        assert code not in weatherfx.CLEAR_CODES


def test_draw_no_crash_across_codes_and_ticks():
    surf = _blank(480, 480)
    rain, cloud, clear = 61, 2, 0
    for code in (rain, cloud, clear):
        for tick in (0, 1, 2):
            weatherfx.draw(surf, code, tick)
            weatherfx.draw(surf, code, tick, x0=0, w=480, h=480)


def test_unknown_code_draws_nothing():
    surf = _blank(500, 480)
    before = pygame.image.tostring(surf, "RGB")
    for code in (4, 50, 100, -5, 999):
        weatherfx.draw(surf, code, 3, x0=0, w=400, h=480)
    after = pygame.image.tostring(surf, "RGB")
    assert before == after


def _assert_confined_to_panel(code, tick):
    w, h = 400, 480
    surf = _blank(w + 100, h)
    beyond = pygame.Rect(w + 11, 0, surf.get_width() - (w + 11), h)
    before_beyond = pygame.image.tostring(surf.subsurface(beyond), "RGB")

    weatherfx.draw(surf, code, tick, x0=0, w=w, h=h)

    after_beyond = pygame.image.tostring(surf.subsurface(beyond), "RGB")
    assert before_beyond == after_beyond, f"code={code} tick={tick} 粒子畫出面板右界外"


def test_rain_particles_confined_to_panel_width():
    for tick in (0, 1, 2, 40):
        _assert_confined_to_panel(61, tick)
    # 額外確認面板內確實有畫到東西（不是整張都沒變化）
    w, h = 400, 480
    surf = _blank(w + 100, h)
    before = pygame.image.tostring(surf, "RGB")
    weatherfx.draw(surf, 61, 3, x0=0, w=w, h=h)
    after = pygame.image.tostring(surf, "RGB")
    assert before != after


def test_cloud_particles_confined_to_panel_width():
    for tick in (0, 1, 2, 200):
        _assert_confined_to_panel(2, tick)
    w, h = 400, 480
    surf = _blank(w + 100, h)
    before = pygame.image.tostring(surf, "RGB")
    weatherfx.draw(surf, 2, 3, x0=0, w=w, h=h)
    after = pygame.image.tostring(surf, "RGB")
    assert before != after


def test_glow_particles_confined_to_panel_width():
    for tick in (0, 1, 2, 30):
        _assert_confined_to_panel(0, tick)
    w, h = 400, 480
    surf = _blank(w + 100, h)
    before = pygame.image.tostring(surf, "RGB")
    weatherfx.draw(surf, 0, 3, x0=0, w=w, h=h)
    after = pygame.image.tostring(surf, "RGB")
    assert before != after


def test_draw_respects_nonzero_x0_offset():
    # x0>0 時，面板右界是 x0+w，左側 x0 之前與右側 x0+w+10 之後都不該被動到。
    w, h, x0 = 300, 480, 100
    surf = _blank(x0 + w + 100, h)
    left = pygame.Rect(0, 0, x0, h)
    beyond = pygame.Rect(x0 + w + 11, 0, surf.get_width() - (x0 + w + 11), h)
    before_left = pygame.image.tostring(surf.subsurface(left), "RGB")
    before_beyond = pygame.image.tostring(surf.subsurface(beyond), "RGB")

    weatherfx.draw(surf, 61, 5, x0=x0, w=w, h=h)

    assert pygame.image.tostring(surf.subsurface(left), "RGB") == before_left
    assert pygame.image.tostring(surf.subsurface(beyond), "RGB") == before_beyond


def test_cache_is_single_slot_not_unbounded():
    """雲層底圖快取只保留「最新一張」：同一組 (code, w, h) 重畫不重建；
    換一組 key 才重建，且重建後只覆蓋掉舊的一張，不是持續累積的容器。"""
    surf = _blank(400, 480)
    weatherfx._cache_key = None
    weatherfx._cache_surface = None
    weatherfx.build_count = 0

    weatherfx.draw(surf, 2, 0, x0=0, w=400, h=480)
    first_count = weatherfx.build_count
    assert first_count == 1
    assert weatherfx._cache_key == (2, 400, 480)

    # 同一組 key 重畫多次：不該重建底圖。
    for tick in range(1, 20):
        weatherfx.draw(surf, 2, tick, x0=0, w=400, h=480)
    assert weatherfx.build_count == first_count

    # 换很多組不同 (code, w, h)：快取仍然只留「最後一組」，不是無界成長的 dict/list。
    # i=0 時 w=400 與目前快取 key 相同不重建，i=1..9 各換一次 key 各重建一次。
    for i in range(10):
        weatherfx.draw(surf, 2, 0, x0=0, w=400 + i, h=480)
    assert weatherfx.build_count == first_count + 9
    assert weatherfx._cache_key == (2, 409, 480)
    assert isinstance(weatherfx._cache_key, tuple)
    # 快取狀態只用兩個純量欄位表示，模組上不存在其他會持續長大的容器屬性。
    assert not hasattr(weatherfx, "_cache_store")
    assert not hasattr(weatherfx, "_cache_list")
