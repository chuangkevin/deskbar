"""deskbar 局部更新 _flip 與 veil 效能優化測試（2026-08-06 實機量測修復）：

- 驗證局部更新時 rot_cache 與 veil 只 blit 髒區域
- 驗證局部更新與全量更新在髒區域內像素完全一致 (行為等價保證)
- 驗證 veil 有作用時，髒區域外像素不被改動，髒區域內有 veil 效果
- 驗證 dirty=None 時全量更新行為不變
- 驗證 dirty 超出畫面邊界時 clipped 生效且不拋出例外
"""
from __future__ import annotations

import threading
import pygame
import pytest

from deskbar import transform
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui.app import App


def _make_real_flip_app(rotation=90) -> App:
    app = App(AppState(), Settings(rotation=rotation), threading.Lock(), on_save=lambda s: None)
    app._dev = False
    app.logical = pygame.Surface((1920, 480))
    app.screen = pygame.Surface((480, 1920))
    return app


@pytest.mark.parametrize("rotation", [90, 270])
def test_flip_dirty_equivalence_with_full(monkeypatch, rotation):
    """行為等價：對同一份 logical 內容，分別跑全量 _flip(None) 與
    「先 _flip(None) 建快取、改動帶狀區域後 _flip(帶狀 rect)」，
    兩者在帶狀對應螢幕區域 (dst_rect) 內的像素必須一致。
    """
    angle = transform.pygame_rotation_angle(rotation)
    monkeypatch.setattr(pygame.display, "flip", lambda: None)

    # 1. 建立基準 app 並畫上基礎底圖
    app = _make_real_flip_app(rotation=rotation)
    for i in range(0, 1920, 160):
        pygame.draw.rect(app.logical, ((i * 7) % 255, (i * 13) % 255, 200),
                         (i, (i // 160) * 24 % 456, 120, 24))

    # 全量更新一次建立 rot_cache 與初始 screen 內容
    app._flip(None)

    # 2. 改動帶狀區域 (中欄 402, 52, 1118, 428)
    band_rect = pygame.Rect(402, 52, 1118, 428)
    pygame.draw.rect(app.logical, (255, 128, 64), band_rect)
    pygame.draw.circle(app.logical, (0, 255, 0), (600, 200), 50)

    # 情況 A：直接跑局部更新
    app._flip(band_rect)
    dirty_screen_bytes = pygame.image.tobytes(app.screen, "RGB")

    # 情況 B：對相同的 logical 內容重新跑全量 _flip(None)
    app_full = _make_real_flip_app(rotation=rotation)
    app_full.logical.blit(app.logical, (0, 0))
    app_full._flip(None)
    full_screen_bytes = pygame.image.tobytes(app_full.screen, "RGB")

    # 算帶狀對應到旋轉 screen 上的 dst_rect
    rot_pos = app._map_rot(band_rect, angle)
    sub_size = pygame.transform.rotate(app.logical.subsurface(band_rect), angle).get_size()
    dst_rect = pygame.Rect(rot_pos, sub_size).clip(app.screen.get_rect())

    # 擷取 dst_rect 內的像素比較
    dirty_sub = app.screen.subsurface(dst_rect)
    full_sub = app_full.screen.subsurface(dst_rect)

    assert pygame.image.tobytes(dirty_sub, "RGB") == pygame.image.tobytes(full_sub, "RGB"), \
        f"{rotation}° 局部更新與全量更新在 dst_rect ({dst_rect}) 内像素不一致"

    # 全全畫面的像素也應該完全相同
    assert dirty_screen_bytes == full_screen_bytes, f"{rotation}° 全畫面像素應該一致"


def test_flip_dirty_with_veil_updates_dirty_only_and_preserves_outside(monkeypatch):
    """veil 有作用時：局部更新後，髒區域內要有 veil 效果，髒區域外的像素不得被改動。"""
    monkeypatch.setattr(pygame.display, "flip", lambda: None)

    app = _make_real_flip_app(rotation=90)
    angle = transform.pygame_rotation_angle(90)

    # 用半透明 (0, 0, 0, 100) 的 veil 模擬亮度疊黑
    veil_surf = pygame.Surface((480, 1920), pygame.SRCALPHA)
    veil_surf.fill((0, 0, 0, 100))
    monkeypatch.setattr(app, "_dim_veil", lambda size: veil_surf)

    # 1. 初始化底圖與 screen
    app.logical.fill((200, 200, 200))
    pygame.draw.rect(app.logical, (255, 0, 0), (100, 100, 200, 200))
    app._flip(None)  # 全量 flip 繪製 initial screen (含 veil)

    screen_before = app.screen.copy()

    # 2. 修改局部區域 (帶狀區域 402, 52, 1118, 428)
    band_rect = pygame.Rect(402, 52, 1118, 428)
    pygame.draw.rect(app.logical, (0, 0, 255), band_rect)

    # 計算旋轉後的 dst_rect
    rot_pos = app._map_rot(band_rect, angle)
    sub_size = pygame.transform.rotate(app.logical.subsurface(band_rect), angle).get_size()
    dst_rect = pygame.Rect(rot_pos, sub_size).clip(app.screen.get_rect())

    # 3. 執行局部 flip
    app._flip(band_rect)

    # 4. 驗證髒區域外 (dst_rect 外) 像素未被修改
    # 把 dst_rect 塗黑後比較
    screen_before_outside = screen_before.copy()
    screen_after_outside = app.screen.copy()
    pygame.draw.rect(screen_before_outside, (0, 0, 0), dst_rect)
    pygame.draw.rect(screen_after_outside, (0, 0, 0), dst_rect)

    assert pygame.image.tobytes(screen_before_outside, "RGB") == \
        pygame.image.tobytes(screen_after_outside, "RGB"), "髒區域外的像素在局部更新時被篡改了！"

    # 5. 驗證髒區域內有 veil 效果 (像素值應比邏輯藍色 (0, 0, 255) 疊黑後更暗)
    # 純 (0, 0, 255) 疊黑 (0, 0, 0, 100) 後的藍色成分約 255 * (255 - 100) / 255 ≈ 155
    dirty_pixel = app.screen.get_at((dst_rect.centerx, dst_rect.centery))
    assert dirty_pixel[2] < 255, f"髒區域內沒有 veil 疊黑效果：{dirty_pixel}"
    assert dirty_pixel[2] > 0, f"髒區域內過暗：{dirty_pixel}"


def test_flip_dirty_none_full_blit_with_veil(monkeypatch):
    """dirty=None 時行為與改動前一致 (整片都有 veil)。"""
    monkeypatch.setattr(pygame.display, "flip", lambda: None)
    app = _make_real_flip_app(rotation=90)

    veil_surf = pygame.Surface((480, 1920), pygame.SRCALPHA)
    veil_surf.fill((0, 0, 0, 128))
    monkeypatch.setattr(app, "_dim_veil", lambda size: veil_surf)

    app.logical.fill((200, 200, 200))
    app._flip(None)

    # 整片畫面都應該被 128 alpha veil 疊黑 (200 * (255 - 128) / 255 ≈ 99)
    top_left = app.screen.get_at((10, 10))
    bottom_right = app.screen.get_at((470, 1910))

    assert abs(top_left[0] - 99) <= 5 and abs(bottom_right[0] - 99) <= 5, \
        f"dirty=None 全量 flip 像素異常: {top_left}, {bottom_right}"


def test_flip_dirty_out_of_bounds_clip(monkeypatch):
    """dirty 給一個超出畫面的矩形 → 不拋例外 (clip 有生效)。"""
    monkeypatch.setattr(pygame.display, "flip", lambda: None)
    app = _make_real_flip_app(rotation=90)
    app._flip(None)  # 先建快取

    # 1. 完全超出畫面的 dirty
    app._flip(pygame.Rect(2500, 2500, 500, 500))
    app._flip(pygame.Rect(-1000, -1000, 500, 500))

    # 2. 部分超出畫面的 dirty
    app._flip(pygame.Rect(1800, 400, 500, 500))
    app._flip((-50, -50, 200, 200))

    # 3. 寬高為 0 的 dirty
    app._flip(pygame.Rect(100, 100, 0, 0))

    # 無例外拋出即通過
