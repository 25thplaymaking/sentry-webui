from pathlib import Path

import pytest

from api.models import Session
from api.routes import _validate_native_runtime_options, _validate_native_workspace_id


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
UI = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
BOOT = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
SESSIONS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
MESSAGES = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")


def test_native_workspace_is_persisted_in_the_session_contract(tmp_path):
    session = Session(
        workspace=tmp_path,
        native_workspace_id="server-work",
        native_runtime_options={"action": "review", "sandbox": "readOnly"},
    )
    assert session.compact()["native_workspace_id"] == "server-work"
    assert session.compact()["native_runtime_options"]["action"] == "review"


def test_native_workspace_id_is_opaque_and_bounded():
    assert _validate_native_workspace_id(" server-work ") == "server-work"
    assert _validate_native_workspace_id(None) is None
    with pytest.raises(ValueError):
        _validate_native_workspace_id("x" * 201)
    with pytest.raises(ValueError):
        _validate_native_workspace_id("bad\nworkspace")


def test_native_controls_are_strict_and_receive_safe_defaults():
    options = _validate_native_runtime_options(
        {"action": "review", "collaboration_mode": "plan", "sandbox": "readOnly"}
    )
    assert options["action"] == "review"
    assert options["collaboration_mode"] == "plan"
    assert options["sandbox"] == "readOnly"
    assert options["approval_policy"] == "on-request"
    with pytest.raises(ValueError):
        _validate_native_runtime_options({"action": "pretend-feature"})
    with pytest.raises(ValueError):
        _validate_native_runtime_options({"arbitrary": True})


def test_codex_work_context_is_hidden_until_a_native_model_is_selected():
    assert 'id="nativeRuntimeBar" role="dialog"' in HTML
    assert 'id="nativeRuntimeComposerWrap" hidden' in HTML
    assert 'id="nativeRuntimeMenuBtn"' in HTML
    assert 'id="nativeWorkspaceSelect"' in HTML
    assert 'id="nativeRuntimeFeatures"' in HTML
    assert "function syncNativeRuntimeBar()" in UI
    assert "wrap.hidden=true" in UI
    assert "_setNativeRuntimeMenuOpen(false)" in UI
    assert "_selectedNativeRuntimeId()" in UI
    assert "Active from your Codex installation" not in HTML
    assert HTML.index('id="composerBox"') < HTML.index('id="nativeRuntimeBar"')


def test_codex_controls_are_real_inputs_and_inventory_is_runtime_driven():
    for control_id in (
        "nativeEffortSelect",
        "nativeSandboxSelect",
        "nativePersonalitySelect",
        "nativeApprovalSelect",
    ):
        assert f'id="{control_id}"' in HTML
    assert "selectNativeRuntimeOption(" in HTML
    assert "_renderNativeRuntimeInventory(runtime)" in UI
    assert "inventory.skills" in UI
    assert "inventory.apps" in UI
    assert "inventory.mcp_servers" in UI
    assert "inventory.plugins" in UI
    assert "inventory.hooks" in UI
    assert 'id="nativePlanToggle"' in HTML
    assert 'id="nativeReviewToggle"' in HTML
    assert "toggleNativeRuntimeQuickOption(" in HTML
    assert "filterNativeRuntimeInventory(" in UI
    assert "Search installed tools" in UI


def test_model_picker_marks_native_models_and_forces_work():
    assert "opt.dataset.nativeRuntime" in UI
    assert "Native Work" in UI
    assert "S._pendingExperience='work'" in BOOT
    assert "await newSession(true,{" in BOOT
    assert "native_workspace_id:nativeWorkspaceId||null" in BOOT


def test_native_workspace_syncs_with_new_and_live_sessions():
    assert "reqBody.native_workspace_id" in SESSIONS
    assert "S._pendingNativeWorkspaceId" in SESSIONS
    assert "'/api/session/update'" in UI
    assert "native_workspace_id:workspaceId" in UI
    assert "reqBody.native_runtime_options" in SESSIONS
    assert "native_runtime_options:options" in UI


def test_native_approvals_and_multi_question_input_use_existing_cards():
    assert "pending.allow_always===false" in MESSAGES
    assert "pending._sentry_native" in MESSAGES
    assert "pending.native_questions" in MESSAGES
    assert "native_answers:nativeAnswers" in MESSAGES
    assert "clarify-native-answer" in MESSAGES


def test_native_runtime_controls_have_disclosure_and_status_semantics():
    assert 'id="nativeRuntimeStatus" role="status" aria-live="polite"' in HTML
    assert 'id="nativeRuntimeFeatures" role="region"' in HTML
    assert 'aria-label="Connected Codex tools and extensions"' in HTML
    assert 'aria-controls="nativeRuntimeFeatures"' in HTML
    assert 'aria-controls="nativeRuntimeBar"' in HTML
    assert 'aria-label="Add Codex context and tools"' in HTML
    assert "panel.setAttribute('aria-hidden',open?'false':'true')" in UI
    assert "function _setNativeRuntimeMenuOpen(open)" in UI
    assert "const first=(workspace&&!workspace.disabled)" in UI
    assert "panel.querySelector('.native-runtime-menu-close')" in UI
    assert "event.key!=='Escape'" in UI


def test_native_runtime_controls_are_touch_and_keyboard_friendly():
    assert ".native-workspace-control select:focus-visible" in CSS
    assert ".native-runtime-features-btn:focus-visible" in CSS
    assert ".native-runtime-menu-btn:focus-visible" in CSS
    assert ".native-runtime-menu-close,.native-runtime-menu-btn{min-width:44px;min-height:44px;}" in CSS
    assert ".native-workspace-control select{width:calc(100% - 35px);max-width:none;min-height:44px" in CSS
    assert ".native-runtime-menu-body{min-height:0;overflow-x:hidden;overflow-y:auto" in CSS
    assert ".native-inventory-search input{min-height:44px;font-size:16px;}" in CSS
    assert "@media(prefers-reduced-motion:reduce)" in CSS


def test_native_setup_uses_one_composer_plus_menu_instead_of_a_control_ribbon():
    assert '<div class="native-runtime-menu" id="nativeRuntimeBar"' in HTML
    assert '<div class="native-runtime-bar" id="nativeRuntimeBar"' not in HTML
    assert 'data-tooltip="Add Codex context and tools"' in HTML
    assert "Add to this task" in HTML
    assert "Files and folders" in HTML
    assert "Plan mode" in HTML
    assert "Review changes" in HTML
    assert "Work settings" in HTML
    assert "Tools and extensions" in HTML
    assert "position:absolute;z-index:220;left:10px;bottom:54px" in CSS
    assert '.native-runtime-menu-btn[aria-expanded="true"]>svg{transform:rotate(45deg);}' not in CSS


def test_workspace_update_failure_is_visible_to_the_user():
    assert "Could not update the local Codex workspace" in UI
    assert "select.setAttribute('aria-busy','true')" in UI
    assert "select.removeAttribute('aria-busy')" in UI
