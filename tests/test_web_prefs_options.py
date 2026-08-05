"""
設定頁是一次 PATCH 全部欄位，任何一個選項值超出後端允許範圍都會讓整頁存不進去，
而且畫面只顯示「儲存失敗」四個字，很難查（2026-08-04 實際踩到：下限從 5 提到 20 之後，選項表的 15 沒跟著改）。
"""

import re
from pathlib import Path

from deskbar.webserver import _PREF_INT


def test_presence_interval_options_within_backend_range():
    html_path = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    match = re.search(r"const\s+spd\s*=\s*\[(.*?)\]\s*;", content)
    assert match is not None, "const spd not found in index.html"

    spd_str = match.group(1)
    values = [int(x) for x in re.findall(r"\d+", spd_str)]
    assert len(values) > 0, "No numerical values extracted from spd"

    lo, hi = _PREF_INT["presence_interval_sec"]
    for val in values:
        assert lo <= val <= hi, f"presence_interval_sec option {val} is out of range [{lo}, {hi}]"


def test_sync_interval_options_within_backend_range():
    html_path = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    match = re.search(r'sel\(\s*"p_si"\s*,\s*\[([0-9,\s]+)\]', content)
    assert match is not None, "sync_interval_min options not found in index.html"

    values = [int(x.strip()) for x in match.group(1).split(",") if x.strip()]
    assert len(values) > 0, "No numerical values extracted for sync_interval_min"

    lo, hi = _PREF_INT["sync_interval_min"]
    for val in values:
        assert lo <= val <= hi, f"sync_interval_min option {val} is out of range [{lo}, {hi}]"
