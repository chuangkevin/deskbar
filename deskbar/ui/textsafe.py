"""文字清理模組 (sanitize_text)

背景（2026-08-05 實機回報）：
便條與待辦（Linear 標題等）常包含 emoji，例如 U+2705 ✅。在 Pi 實機上只有
Noto Sans CJK，沒有安裝任何 emoji 字型（`fc-list | grep -i emoji` 回傳空），
導致缺字繪製成豆腐框 (⊠)。

注意：pygame.font.Font.metrics() 對缺字會回傳 .notdef 的度量、聲稱「有字形」，
2026-08-05 實測踩過這個坑，完全不可信；必須在渲染前進行靜態字串清理與動態像素比對。
"""
import re

# 模組層級等義替換表：常見 emoji 替換為 Noto Sans CJK 有涵蓋的相近符號
EMOJI_REPLACEMENTS: dict[str, str] = {
    # 打勾符號 -> ✓ (U+2713)
    "\u2705": "✓",  # ✅ WHITE HEAVY CHECK MARK
    "\u2714": "✓",  # ✔ HEAVY CHECK MARK
    "\u2611": "✓",  # ☑ BALLOT BOX WITH CHECK
    # 叉叉符號 -> × (U+00D7)
    "\u274c": "×",  # ❌ CROSS MARK
    "\u2716": "×",  # ✖ HEAVY MULTIPLICATION X
    "\u2717": "×",  # ✗ BALLOT X
    "\u274e": "×",  # ❎ NEGATIVE SQUARED CROSS MARK
    # 星形符號 -> ★ (U+2605)
    "\u2b50": "★",  # ⭐ WHITE MEDIUM STAR
    "\U0001f31f": "★",  # 🌟 GLOWING STAR
    # 圓點／色塊 indicators -> ● (U+25CF)
    "\U0001f534": "●",  # 🔴 RED CIRCLE
    "\U0001f535": "●",  # 🔵 BLUE CIRCLE
    "\U0001f7e0": "●",  # 🟠 ORANGE CIRCLE
    "\U0001f7e1": "●",  # 🟡 YELLOW CIRCLE
    "\U0001f7e2": "●",  # 🟢 GREEN CIRCLE
    "\U0001f7e3": "●",  # 🟣 PURPLE CIRCLE
    "\U0001f7e4": "●",  # 🟣 PURPLE CIRCLE
    "\U0001f7e5": "●",  # 🟤 BROWN CIRCLE
    "\U0001f7e6": "●",  # 🟦 LARGE BLUE SQUARE
    "\U0001f7e7": "●",  # 🟧 LARGE ORANGE SQUARE
    "\U0001f7e8": "●",  # 🟨 LARGE YELLOW SQUARE
    "\U0001f7e9": "●",  # 🟩 LARGE GREEN SQUARE
    "\U0001f7ea": "●",  # 🟪 LARGE PURPLE SQUARE
    "\U0001f7eb": "●",  # 🟫 LARGE BROWN SQUARE
    "\u26ab": "●",  # ⚫ MEDIUM BLACK CIRCLE
    "\u26aa": "●",  # ⚪ MEDIUM WHITE CIRCLE
    "\U0001f4a1": "●",  # 💡 ELECTRIC LIGHT BULB
    "\U0001f4cc": "●",  # 📌 PUSHPIN
    "\U0001f525": "●",  # 🔥 FIRE
}

# A1. 無寬度控制字元（單獨 render 會拋 pygame.error: Text has zero width 例外）：
# U+FE00–U+FE0F (變體選擇符)、U+200D (ZWJ)、U+200B–U+200F、U+1F3FB–U+1F3FF (膚色修飾符)
_ZERO_WIDTH_PATTERN = re.compile(r"[\ufe00-\ufe0f\u200d\u200b-\u200f\U0001f3fb-\U0001f3ff]")

_REPLACEMENT_TABLE = str.maketrans(EMOJI_REPLACEMENTS)


def sanitize_text(s: str) -> str:
    """純函數：渲染前靜態字串清理（不碰 pygame、不做 I/O）。

    A1. 刪除無寬度控制字元（變體選擇符 VS1-16、ZWJ、膚色修飾符等）。
    A2. 套用等義替換表，將常見 emoji 替換為 Noto CJK 涵蓋的符號。
    A3. 刪除所有 codepoint > 0xFFFF 的星形平面字元（Pi 上無字型涵蓋）。
    """
    if not s:
        return ""

    # A1. 先刪除無寬度控制字元
    s1 = _ZERO_WIDTH_PATTERN.sub("", s)
    if not s1:
        return ""

    # A2. 套用等義替換表
    s2 = s1.translate(_REPLACEMENT_TABLE)

    # A3. 刪除 codepoint > 0xFFFF 的星形平面字元
    res = [ch for ch in s2 if ord(ch) <= 0xFFFF]
    return "".join(res)
