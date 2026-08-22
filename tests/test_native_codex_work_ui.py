from pathlib import Path

import pytest

from api.models import Session
from api.routes import _validate_native_workspace_id


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
UI = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
BOOT = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
SESSIONS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
MESSAGES = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")


def test_native_workspace_is_persisted_in_the_session_contract(tmp_path):
    session = Session(workspace=tmp_path, native_workspace_id="server-work")
    assert session.compact()["native_workspace_id"] == "server-work"


def test_native_workspace_id_is_opaque_and_bounded():
    assert _validate_native_workspace_id(" server-work ") == "server-work"
    assert _validate_native_workspace_id(None) is None
    with pytest.raises(ValueError):
        _validate_native_workspace_id("x" * 201)
    with pytest.raises(ValueError):
        _validate_native_workspace_id("bad\nworkspace")


def test_codex_work_context_is_hidden_until_a_native_model_is_selected():
    assert 'id="nativeRuntimeBar" hidden' in HTML
    assert 'id="nativeWorkspaceSelect"' in HTML
    assert 'id="nativeRuntimeFeatures"' in HTML
    assert "function syncNativeRuntimeBar()" in UI
    assert "bar.hidden=true" in UI
    assert "_selectedNativeRuntimeId()" in UI


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


def test_native_approvals_and_multi_question_input_use_existing_cards():
    assert "pending.allow_always===false" in MESSAGES
    assert "pending._sentry_native" in MESSAGES
    assert "pending.native_questions" in MESSAGES
    assert "native_answers:nativeAnswers" in MESSAGES
    assert "clarify-native-answer" in MESSAGES


def test_native_runtime_controls_have_disclosure_and_status_semantics():
    assert 'id="nativeRuntimeStatus" role="status" aria-live="polite"' in HTML
    assert 'id="nativeRuntimeFeatures" role="region"' in HTML
    assert 'aria-controls="nativeRuntimeFeatures"' in HTML
    assert "panel.setAttribute('aria-hidden',open?'false':'true')" in UI
    assert "event.key!=='Escape'" in UI


def test_native_runtime_controls_are_touch_and_keyboard_friendly():
    assert ".native-workspace-control select:focus-visible" in CSS
    assert ".native-runtime-features-btn:focus-visible" in CSS
    assert ".native-workspace-control select{max-width:none;width:100%;min-height:44px;font-size:16px;}" in CSS
    assert ".native-runtime-features-btn{min-height:44px" in CSS
    assert "@media(prefers-reduced-motion:reduce)" in CSS


def test_workspace_update_failure_is_visible_to_the_user():
    assert "Could not update the local Codex workspace" in UI
    assert "select.setAttribute('aria-busy','true')" in UI
    assert "select.removeAttribute('aria-busy')" in UI
