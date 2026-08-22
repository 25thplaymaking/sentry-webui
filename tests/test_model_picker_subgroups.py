from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
UI=(ROOT/"static"/"ui.js").read_text(encoding="utf-8")
CSS=(ROOT/"static"/"style.css").read_text(encoding="utf-8")

def test_vendor_subgroup_allowlist():
    assert "SUB_GROUP_PROVIDERS" in UI
    assert "openrouter" in UI
    assert "nous" in UI

def test_vendor_prefix_strips_routing_prefix():
    # The strip pattern must match the existing normalizer at line 1749
    assert "replace(/^@([^:]+:)+/,'')" in UI
    assert re.search(r"indexOf\('/'\)|split\('/'\)", UI)

def test_subgroup_keys_use_double_colon_separator():
    assert "::" in UI
    assert re.search(r"_groupOpenState\[subKey\]", UI)

def test_single_model_vendor_buckets_stay_flat():
    # pfxRows.length>=2 gate means single-model prefixes render flat
    assert re.search(r"\.length\s*>=\s*2", UI)

def test_visible_rows_walk_all_group_body_ancestors():
    visible_match=re.search(r"const _visibleModelRows=\(\)=>[\s\S]+?\}\);", UI)
    assert visible_match, "_visibleModelRows definition not found"
    visible=visible_match.group(0)
    assert "while(" in visible
    assert "parentElement" in visible
    assert "model-group-body" in visible
    assert "closest('.model-group-body')" not in visible

def test_nested_group_css_exists():
    assert ".model-group.sub" in CSS
    assert ".model-group-body.sub" in CSS


def test_large_catalog_opens_only_the_selected_vendor_subgroup():
    assert "const _selectedVendorPrefix=" in UI
    assert "const sibling=_modelData.find" in UI
    assert "const _selectedSubGroupKey=" in UI
    assert "_groupOpenState[subKey]=(subKey===_selectedSubGroupKey)" in UI


def test_native_runtime_groups_are_prioritized_without_reordering_models():
    assert "const _displayGroupOrder=[..._groupOrder].sort" in UI
    assert "optgroup?.dataset?.nativeRuntime" in UI
    assert "for(const groupKey of _displayGroupOrder)" in UI


def test_picker_disclosures_and_rows_are_keyboard_operable():
    assert "heading.setAttribute('aria-expanded'" in UI
    assert "subHeading.setAttribute('aria-expanded'" in UI
    assert "row.setAttribute('role','button')" in UI
    assert "e.key!=='Enter'&&e.key!==' '" in UI
    assert ".model-opt:focus-visible" in CSS


def test_escape_returns_focus_to_the_visible_mobile_model_trigger():
    assert "mobilePanel.classList.contains('open')" in UI
    assert "?'composerMobileModelAction'" in UI
    assert "renderModelDropdown({triggerId})" in UI
    assert "trigger.focus({preventScroll:true})" in UI
    assert "modelDropdown.classList.contains('open')" in UI
    assert "modelAction.focus({preventScroll:true})" in UI


def test_desktop_picker_focuses_search_after_becoming_visible():
    assert "dd.classList.add('open')" in UI
    assert "if(input&&dd.classList.contains('open')) input.focus({preventScroll:true})" in UI
