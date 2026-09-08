from pathlib import Path
import re


HTML_PATH = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _usage_block(content: str) -> str:
    start = content.index("const USAGE_PROVIDER_META")
    end = content.index("async function savePrefs")
    return content[start:end]


def _function_block(content: str, name: str, next_name: str) -> str:
    start = content.index(f"function {name}")
    end = content.index(f"function {next_name}", start)
    return content[start:end]


def _media_rule(content: str, width: str) -> str:
    match = re.search(rf"@media\(max-width:{re.escape(width)}\)\{{([^}}]+(?:\}}[^@}}]+)*)\}}", content)
    assert match is not None, f"missing max-width:{width} media rule"
    return match.group(0)


def test_usage_source_card_view_order_and_collapsed_ids():
    content = _html()
    block = _function_block(content, "renderUsageSourceView", "statusForUsageSource")

    identity_idx = block.index('class:"usage-card-identity"')
    status_idx = block.index("statusForUsageSource(source)")
    time_idx = block.index("usageObservationText(source)")
    metrics_idx = block.index("renderUsageMetricRows(source)")
    actions_idx = block.index("card.appendChild(actions)")
    details_idx = block.index("renderUsageSourceDetails(source)")
    assert identity_idx < status_idx < time_idx < metrics_idx < actions_idx < details_idx

    assert "來源資訊" in block
    assert "來源 ID" in block
    assert "帳號 ID" in block
    assert "來源類型" in block
    assert "data-source-id" not in block
    assert '"帳號："+' not in block
    assert '"・ID："+' not in block


def test_usage_source_mobile_actions_are_two_column_touch_grid():
    content = _html()
    media = _media_rule(content, "767px")

    assert ".usage-card-actions{display:grid" in media
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in media
    assert ".usage-card-actions button" in media
    assert "min-height:44px" in media
    assert "white-space:normal" in media
    assert "writing-mode" not in content


def test_usage_source_plain_language_labels_and_metric_names():
    content = _html()
    block = _usage_block(content)

    for label in ["用量更新時間：", "本週", "5小時", "本日"]:
        assert label in block

    for removed in [
        "觀測時間：",
        "Custom source token",
        "scoped token",
        "localStorage",
        "provider_account_id</span>",
        "account id",
        "OAuth",
    ]:
        assert removed not in content

    assert "新增來源不會替你登入其他帳號" in content
    assert "回報金鑰" in content
    assert "管理金鑰" in content
    assert "X-Deskbar-Source-Token: <回報金鑰>" in content
