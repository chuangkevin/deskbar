from pathlib import Path
import re


HTML_PATH = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _usage_script_block(content: str) -> str:
    start = content.index("const USAGE_PROVIDER_META")
    end = content.index("async function savePrefs")
    return content[start:end]


def test_usage_source_manager_markup_and_legacy_controls_are_present():
    content = _html()

    for marker in [
        'id="usage-source-manager"',
        'id="usage-source-list"',
        'id="usage-archived-list"',
        'id="usage-add-form"',
        'id="usage-auth-panel"',
        'type="password" id="usage-management-token"',
        'id="usage-token-retry"',
        "舊版來源",
    ]:
        assert marker in content

    for provider in ["openai", "claude", "antigravity", "custom"]:
        assert f'<option value="{provider}">' in content

    # The existing /api/prefs usage_sources checkboxes remain compatible.
    assert 'class="p_us"' in content
    assert 'document.querySelectorAll(".p_us:checked")' in content
    assert "usage_sources:" in content


def test_usage_source_rendering_uses_dom_text_not_raw_source_html():
    content = _html()
    block = _usage_script_block(content)

    assert ".textContent" in block
    assert "document.createElement" in block
    assert ".innerHTML" not in block
    assert "insertAdjacentHTML" not in block
    assert "${source." not in block
    assert "received_at" not in block


def test_usage_source_status_auth_and_error_contracts_are_visible():
    content = _html()
    block = _usage_script_block(content)

    for text in ["等待收集器回報", "暫停收集", "已過期", "等待回報", "正常"]:
        assert text in block

    assert "#67c8ff" in content
    assert "#f5a76c" in content
    assert "include_archived=1" in block
    assert "r.status===503" in block
    assert "用量來源儲存目前無法讀取" in block
    assert "X-Deskbar-Token" in content
    assert "r.status===401" in block
    assert "usageSourcesState.pendingRetry" in block
    assert "localStorage." not in content


def test_usage_source_mutations_are_explicit_and_check_response_status():
    content = _html()
    block = _usage_script_block(content)

    for fn in [
        "saveUsageSourceEdit",
        "saveNewUsageSource",
        "archiveUsageSource",
        "restoreUsageSource",
        "rotateUsageSourceToken",
        "moveUsageSource",
    ]:
        assert f"function {fn}" in block or f"async function {fn}" in block

    assert "if(!r.ok)" in block
    assert "confirm(" in block
    assert "/api/usage-sources/\"+encodeURIComponent(sourceId)+\"/token" in block
    assert "USAGE_METRIC_RE.test" in block
    assert "stale<1||stale>720" in block
    assert "provider===\"openai\"&&!account" in block


def test_usage_source_polling_preserves_focused_or_editing_cards():
    content = _html()
    block = _usage_script_block(content)

    assert "setInterval" in block
    assert "15000" in block
    assert "isPrefsSectionVisible()" in block
    assert "usageSourcesState.editingId===id||activeInside" in block
    assert "card.dataset.hash!==hash" in block


def test_usage_source_responsive_css_contract():
    content = _html()

    for width in ["390px", "768px", "820px", "1440px"]:
        assert width in content

    for css in [
        ".usage-grid{display:grid",
        "grid-template-columns:repeat(2,minmax(0,1fr))",
        "grid-template-columns:repeat(3,minmax(0,1fr))",
        "min-height:44px",
        "min-width:0",
        "overflow-wrap:anywhere",
        ".source-snippet{display:block;overflow-x:auto",
    ]:
        assert css in content

    assert re.search(r"@media\(max-width:767px\).*usage-actions button", content)
