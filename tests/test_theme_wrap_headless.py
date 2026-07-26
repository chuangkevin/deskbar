"""量測式文字截斷／換行共用工具（theme.truncate_to_width／theme.wrap_lines）：
事件塊標題、agenda 卡片標題、詳情描述都靠這兩支純函數決定實際要畫什麼字，
這裡直接對函數本身釘住行為，不必透過完整畫面渲染間接驗證。"""
from deskbar.ui import theme


def test_truncate_returns_original_when_it_fits():
    f = theme.font(22)
    text = "會議"
    assert theme.truncate_to_width(text, f, f.size(text)[0] + 10) == text


def test_truncate_adds_ellipsis_when_too_long():
    f = theme.font(22)
    text = "一個很長很長的事件標題"
    full_w = f.size(text)[0]
    truncated = theme.truncate_to_width(text, f, full_w / 2)
    assert truncated.endswith("…")
    assert f.size(truncated)[0] <= full_w / 2
    assert len(truncated) < len(text)


def test_truncate_returns_empty_when_not_even_one_char_fits():
    f = theme.font(22)
    assert theme.truncate_to_width("會議", f, 1) == ""


def test_truncate_empty_input_returns_empty():
    f = theme.font(22)
    assert theme.truncate_to_width("", f, 100) == ""


def test_wrap_lines_single_line_when_it_fits():
    f = theme.font(22)
    text = "短標題"
    lines = theme.wrap_lines(text, f, f.size(text)[0] + 10, 2)
    assert lines == [text]


def test_wrap_lines_caps_at_max_lines_with_ellipsis():
    f = theme.font(22)
    text = "中文測試換行邏輯是否可以正常運作而不會出現任何錯誤或例外狀況發生於此地"
    lines = theme.wrap_lines(text, f, 150, 2)
    assert len(lines) == 2
    assert lines[-1].endswith("…")
    for line in lines:
        assert f.size(line)[0] <= 150


def test_wrap_lines_english_does_not_break_word_mid_way():
    f = theme.font(22)
    text = "This is a sentence with several distinct English words to wrap"
    words = set(text.split(" "))
    lines = theme.wrap_lines(text, f, 140, 2)
    assert len(lines) <= 2
    for line in lines:
        tokens = line.split(" ")
        if tokens and tokens[-1].endswith("…"):
            tokens[-1] = tokens[-1][:-1]
        for token in tokens:
            if token:
                assert token in words, f"word broken mid-way: {token!r}"


def test_wrap_lines_zero_max_lines_returns_empty():
    f = theme.font(22)
    assert theme.wrap_lines("任何文字", f, 200, 0) == []


def test_wrap_lines_empty_text_returns_empty():
    f = theme.font(22)
    assert theme.wrap_lines("", f, 200, 2) == []
