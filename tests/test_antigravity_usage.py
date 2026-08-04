"""antigravity_usage 解析與工具單元測試。"""
import ast
import builtins
from pathlib import Path

from tools.antigravity_usage import _parse_refresh_minutes, parse_usage_panel

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "antigravity_usage_panel.txt"



def test_parse_usage_panel_with_fixture():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    res = parse_usage_panel(text)

    assert res["gemini_weekly_remaining"] == 94.04
    assert res["gemini_weekly_refresh_min"] == 9869   # 164h 29m = 164*60 + 29 = 9869
    assert res["gemini_5h_remaining"] == 64.24
    assert res["gemini_5h_refresh_min"] == 89         # 1h 29m = 60 + 29 = 89


def test_parse_usage_panel_ignores_claude_and_gpt_section():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    res = parse_usage_panel(text)

    # 確定沒有把 CLAUDE AND GPT MODELS 的 66.03% 與 0.00% 混進 Gemini
    assert res["gemini_weekly_remaining"] != 66.03
    assert res["gemini_5h_remaining"] != 0.00


def test_parse_usage_panel_zero_percent_without_remaining_prefix():
    # 測試 0.00% 時無 "N% remaining ·" 前綴的重置時間抓取特判
    raw = """
GEMINI MODELS
  Models within this group: Gemini Flash, Gemini Pro

  Five Hour Limit
    [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.00%
    Refreshes in 1h 32m
"""
    res = parse_usage_panel(raw)
    assert res["gemini_5h_remaining"] == 0.00
    assert res["gemini_5h_refresh_min"] == 92         # 1h 32m = 60 + 32 = 92


def test_parse_usage_panel_handles_empty_garbage_and_missing_section():
    for empty in ("", "   ", "random noise", "CLAUDE AND GPT MODELS\n[███] 50.00%\nRefreshes in 1h"):
        res = parse_usage_panel(empty)
        assert res["gemini_5h_remaining"] is None
        assert res["gemini_5h_refresh_min"] is None
        assert res["gemini_weekly_remaining"] is None
        assert res["gemini_weekly_refresh_min"] is None


def test_parse_refresh_minutes_formats():
    assert _parse_refresh_minutes("164h 29m") == 9869
    assert _parse_refresh_minutes("1h 29m") == 89
    assert _parse_refresh_minutes("29m") == 29
    assert _parse_refresh_minutes("2d 3h") == 3060     # 2*1440 + 3*60 = 3060
    assert _parse_refresh_minutes("") is None
    assert _parse_refresh_minutes("invalid") is None


def test_module_has_no_undefined_module_references():
    """靜態檢查 tools/antigravity_usage.py 中是否有未定義的模組引用。

    動機：fetch_usage_text 的例外全被 except Exception 吞掉，
    NameError 這類打字錯誤不會讓測試變紅，只會讓抓取靜默失效
    （2026-08-04 實際踩到：termios 忘了 import）。
    """
    target_path = Path(__file__).parent.parent / "tools" / "antigravity_usage.py"
    source = target_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_level_imports = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                name = alias.asname if alias.asname else alias.name.split(".")[0]
                top_level_imports.add(name)
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                name = alias.asname if alias.asname else alias.name
                top_level_imports.add(name)

    builtin_names = set(dir(builtins))
    missing_references = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_name = node.name
            local_names = set()
            for child in ast.walk(node):
                if isinstance(child, ast.arg):
                    local_names.add(child.arg)
                elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    local_names.add(child.id)

            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    var_id = child.value.id
                    if (
                        var_id not in top_level_imports
                        and var_id not in local_names
                        and var_id not in builtin_names
                    ):
                        missing_references.append((func_name, var_id))

    assert not missing_references, f"Found undefined module references: {missing_references}"

