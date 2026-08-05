"""文字渲染安全與缺字清理測試 (tests/test_textsafe.py)

背景與原因（2026-08-05 實機回報）：
便條與待辦（Linear 標題等）常包含 emoji，如 U+2705 ✅。在 Raspberry Pi 實機上僅安裝
Noto Sans CJK，未安裝任何 emoji 字型（`fc-list | grep -i emoji` 回傳空），導致缺字劃成豆腐框 (⊠)。

 pygame.font.Font.metrics() 對缺字會回傳 .notdef 度量，聲稱「字形存在」，2026-08-05 實測踩過此坑，
完全不可信；必須在渲染前透過 sanitize_text() 純函數清理，並於 cache miss 時比對 U+E000 豆腐特徵碼 (tofu signature)。
"""
import pygame

from deskbar.ui import theme
from deskbar.ui.textsafe import sanitize_text


def test_sanitize_text_check_mark():
    assert sanitize_text("已做好✅; 待部署") == "已做好✓; 待部署"


def test_sanitize_text_vs16_combination():
    # U+2714 (✔) + U+FE0F (VS16) + 完成 -> VS16 先被 A1 刪除、✔ 再被 A2 替換為 ✓
    assert sanitize_text("✔️完成") == "✓完成"


def test_sanitize_text_colored_circles():
    assert sanitize_text("🔴 高優先") == "● 高優先"


def test_sanitize_text_astral_plane_removal():
    # codepoint > 0xFFFF 的星形平面字元 (🚀 U+1F680, 🎉 U+1F389) 一律刪除
    assert sanitize_text("看這裡🚀🎉") == "看這裡"


def test_sanitize_text_valid_symbols_preserved():
    # ⚠ (U+26A0), → (U+2192), ✓ (U+2713) 均為 Noto CJK 支援之可用符號，保持原樣
    assert sanitize_text("⚠ 注意 → 下一步 ✓") == "⚠ 注意 → 下一步 ✓"


def test_sanitize_text_ascii_and_cjk_unmodified():
    assert sanitize_text("純中文與 ASCII 不動") == "純中文與 ASCII 不動"


def test_sanitize_text_empty_input():
    assert sanitize_text("") == ""


def test_sanitize_text_emoji_only_returns_empty():
    assert sanitize_text("🚀🎉") == ""


def test_text_surface_with_emoji_check_mark():
    surf = theme.text_surface("已做好✅", 20, (255, 255, 255))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_width() > 0


def test_text_surface_with_single_emoji_replacement():
    surf = theme.text_surface("✅", 20, (255, 255, 255))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_width() > 0


def test_text_surface_with_pure_astral_emoji():
    # 清理後為空字串，不得拋出例外，且需回傳合法 Surface (1x1 透明面)
    surf = theme.text_surface("🚀", 20, (255, 255, 255))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_width() > 0
    assert surf.get_height() > 0


def test_text_surface_with_pure_variation_selector():
    # 純變體選擇符 U+FE0F，實測會拋 pygame.error: Text has zero width，清理後為空字串，不得拋例外
    surf = theme.text_surface("\ufe0f", 20, (255, 255, 255))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_width() > 0
    assert surf.get_height() > 0
