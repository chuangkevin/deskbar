from pathlib import Path


HTML_PATH = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"


def _usage_script_block() -> str:
    content = HTML_PATH.read_text(encoding="utf-8")
    start = content.index("const USAGE_PROVIDER_META")
    end = content.index("async function savePrefs")
    return content[start:end]


def test_usage_source_cards_track_rendered_mode_separately_from_hash():
    block = _usage_script_block()

    assert "function usageSourceMode" in block
    assert 'card.dataset.mode=mode||usageSourceMode(source,archived)' in block
    assert "card.dataset.mode!==mode" in block

    hash_start = block.index("function usageSourceHash")
    hash_end = block.index("function renderUsageSourceCard")
    hash_block = block[hash_start:hash_end]
    assert "editingId" not in hash_block
    assert "dataset.mode" not in hash_block


def test_usage_source_replacement_removes_same_id_duplicates():
    block = _usage_script_block()

    assert "existing.has(id)){card.remove();continue}" in block
    assert "card.replaceWith(nextCard)" in block
    assert "container.appendChild(card)" in block
    assert "!wanted.has(card.dataset.sourceId))card.remove()" in block


def test_usage_source_editor_refresh_keeps_draft_but_mode_transition_repaints():
    block = _usage_script_block()

    assert 'keepDraft=card&&card.dataset.mode==="editor"&&mode==="editor"' in block
    assert "sourceChanged=card&&card.dataset.hash!==hash" in block
    assert "modeChanged=card&&card.dataset.mode!==mode" in block
    assert "usageSourcesState.editingId===id||activeInside" in block
