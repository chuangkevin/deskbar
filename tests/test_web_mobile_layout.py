"""
Static contract tests for Deskbar web control page mobile layout,
sticky navigation, accessibility, and note card RWD rules.
"""

from pathlib import Path
import re


def _get_html_content() -> str:
    html_path = Path(__file__).parent.parent / "deskbar" / "web" / "index.html"
    assert html_path.exists(), "index.html must exist"
    return html_path.read_text(encoding="utf-8")


def test_sticky_nav_and_section_anchors():
    content = _get_html_content()
    # Sticky nav element with aria-label
    assert '<nav class="sticky-nav" aria-label="頁面快速導航">' in content

    # 4 anchor targets
    for target in ['#sec-notes', '#sec-alarms', '#sec-cals', '#sec-prefs']:
        assert f'href="{target}"' in content

    # 4 heading IDs on h2 elements
    for heading_id in ['sec-notes', 'sec-alarms', 'sec-cals', 'sec-prefs']:
        assert f'id="{heading_id}"' in content


def test_overflow_and_reduced_motion_rules():
    content = _get_html_content()
    # Body overflow-x hidden
    assert "overflow-x:hidden" in content or "overflow-x: hidden" in content

    # Nav sticky position and overflow-x: auto (only on sticky-nav)
    assert ".sticky-nav" in content
    assert "overflow-x:auto" in content or "overflow-x: auto" in content

    # reduced-motion rule exists
    assert "prefers-reduced-motion" in content
    assert "scroll-behavior" in content


def test_responsive_breakpoints_and_note_card_rules():
    content = _get_html_content()
    # Mobile and Tablet/Desktop breakpoints
    assert "768px" in content
    assert "min-height:44px" in content or "min-height: 44px" in content

    # min-width: 0 and word wrapping contract
    assert "min-width:0" in content or "min-width: 0" in content
    assert ("overflow-wrap:anywhere" in content or "overflow-wrap: anywhere" in content or
            "word-break:break-word" in content or "word-break: break-word" in content)

    # Precise touch target contract for .color-btn (width/height/min-width/min-height >= 44px)
    color_btn_match = re.search(r'\.color-btn\s*\{([^}]+)\}', content)
    assert color_btn_match is not None, ".color-btn CSS rule must exist"
    color_btn_style = color_btn_match.group(1)
    for dim in ["width", "height", "min-width", "min-height"]:
        val_match = re.search(rf'{dim}:\s*(\d+)px', color_btn_style)
        assert val_match is not None, f".color-btn must specify {dim}"
        assert int(val_match.group(1)) >= 44, f".color-btn {dim} must be at least 44px"


def test_render_notes_semantic_classes_and_handlers():
    content = _get_html_content()
    # Semantic classes in renderNotes
    for cls_name in ["note-card-head", "note-body", "note-actions", "note-colors", "note-drag-handle"]:
        assert cls_name in content

    # Handlers & operation semantics
    for handler in ["dragStart(event)", "editingNote=", "delNote(", "setColor(", "saveEdit("]:
        assert handler in content

    # Accessibility attributes on drag handle and color buttons
    assert 'aria-label="拖曳排序"' in content
    assert "touch-action:none" in content or "touch-action: none" in content


def test_prefs_interval_options_integrity():
    content = _get_html_content()
    # Assert exact interval arrays remain intact as specified in requirements
    match_spd = re.search(r'const\s+spd\s*=\s*\[\[20,\s*"快"\]\s*,\s*\[30,\s*"中"\]\s*,\s*\[45,\s*"慢"\]\]\s*;', content)
    assert match_spd is not None, "spd array must match exact interval options"

    match_psi = re.search(r'sel\(\s*"p_si"\s*,\s*\[1\s*,\s*3\s*,\s*5\s*,\s*10\s*,\s*30\]\s*,', content)
    assert match_psi is not None, "p_si sync interval options array must match exact options"


def test_sticky_nav_click_handler_contract():
    content = _get_html_content()
    # Sticky nav click handler query selector and click listener
    assert '.sticky-nav a[href^="#sec-"]' in content
    assert 'addEventListener("click"' in content or "addEventListener('click'" in content

    # Missing target guard before preventDefault
    assert "!target" in content
    assert "preventDefault" in content

    # reduced-motion matchMedia check selecting auto or smooth
    assert "prefers-reduced-motion: reduce" in content or "prefers-reduced-motion:reduce" in content
    assert "matchMedia" in content
    assert '"auto"' in content or "'auto'" in content
    assert '"smooth"' in content or "'smooth'" in content

    # scrollIntoView with block start
    assert "scrollIntoView" in content
    assert 'block:"start"' in content or 'block: "start"' in content or 'block:\'start\'' in content

    # URL hash update using history API or location.hash
    assert "history.pushState" in content or "location.hash" in content

