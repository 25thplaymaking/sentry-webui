from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANELS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
UI = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
FRONTIR = (ROOT / "static" / "frontir.js").read_text(encoding="utf-8")


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    quote = None
    escaped = False
    for index in range(brace, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise AssertionError(f"could not find end of {signature}")


def test_sentry_profile_chip_routes_to_behavior_without_opening_dropdown():
    body = _function_body(PANELS, "function toggleProfileDropdown(e)")
    guard = body.index("_isSentryProductMode()")
    route = body.index("switchPanel('profiles')", guard)
    shell = body.index("_openProfileDropdownShell()")

    assert guard < route < shell
    assert "closeProfileDropdown();" in body[guard:route]
    assert "return;" in body[route:shell]


def test_sentry_profile_panel_edits_the_real_profile_soul():
    load_start = PANELS.index("async function loadProfilesPanel()")
    load_end = PANELS.index("function _renderSentryProfileBehavior", load_start)
    load = PANELS[load_start:load_end]
    save = _function_body(PANELS, "async function saveSentryProfileBehavior()")

    assert "data.single_profile_mode" in load
    assert "_renderSentryProfileBehavior" in load
    assert "await api('/api/memory')" in load
    assert "'/api/memory/write'" in save
    assert "section: 'soul'" in save
    assert "SENTRY_PROFILE_BEHAVIOR_MAX_CHARS" in save


def test_sentry_labels_the_control_and_panel_as_agent_behavior():
    configure = _function_body(PANELS, "function _configureSentryNavigation()")

    assert "_setSentryNavigationLabel('profiles','Agent behavior')" in configure
    assert "Agent behavior" in configure
    assert "sentry-profile-behavior-chip" in configure
    assert "title:'Agent behavior'" in PANELS
    assert "if(panel==='profiles'&&_isSentryProductMode()) mainText='Agent behavior';" in PANELS
    assert "name.title='Agent behavior'" in FRONTIR


def test_sentry_chip_label_is_behavior_but_stock_profile_source_is_preserved():
    assignments = [
        line for line in UI.splitlines()
        if "profileLabel.textContent=" in line or "_profileLabel.textContent=" in line
    ]
    assert assignments
    assert sum("_profileChipDisplayLabel" in line for line in assignments) >= 2
    assert sum("S.activeProfile||'default'" in line for line in assignments) >= 2
    helper = _function_body(PANELS, "function _profileChipDisplayLabel()")
    assert "_isSentryProductMode()" in helper
    assert "S.activeProfile" in helper
    assert "'Behavior'" in helper


def test_non_sentry_multi_profile_switching_remains_available():
    body = _function_body(PANELS, "function toggleProfileDropdown(e)")

    assert "renderProfileDropdown(cached)" in body
    assert "_profileDropdownFetchFresh()" in body
    assert "if (data.single_profile_mode)" in body
