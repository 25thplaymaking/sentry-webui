"""Sentry Chat and Work are persisted lanes, not a cosmetic client toggle."""

from pathlib import Path

import api.models as models
import api.routes as routes


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_session_defaults_to_work():
    session = models.Session(workspace=str(ROOT))
    assert session.experience == "work"
    assert session.compact()["experience"] == "work"


def test_chat_session_round_trips_through_compact_projection():
    session = models.Session(workspace=str(ROOT), experience="chat")
    assert session.compact()["experience"] == "chat"


def test_new_session_request_experience_validation_is_strict():
    assert routes._validate_session_experience("chat") == "chat"
    assert routes._validate_session_experience("WORK") == "work"
    try:
        routes._validate_session_experience("unrestricted")
    except ValueError as exc:
        assert "chat" in str(exc) and "work" in str(exc)
    else:
        raise AssertionError("unknown experience must be refused")


def test_hidden_child_sessions_cannot_upgrade_chat_to_work():
    source = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    btw = source[source.index("def _handle_btw("):source.index("def _handle_background(")]
    background = source[source.index("def _handle_background("):source.index("def _checkpoint_user_message_for_eager_session_save(")]
    inheritance = "experience=getattr(s, 'experience', 'work')"
    assert inheritance in btw
    assert inheritance in background


def test_ui_has_first_class_chat_work_switch_and_no_subscription_picker_duplicate():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    ui = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
    admin = (ROOT / "static" / "agent_admin.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert 'id="experienceBar"' in html
    assert "selectExperience('chat')" in html
    assert "selectExperience('work')" in html
    assert "async function selectExperience" in ui
    assert "window._modelCatalogRestricted" in ui
    assert ui.count("if(!window._modelCatalogRestricted){") >= 2
    assert "SUB_GROUP_PROVIDERS.has(String(meta.key||meta.providerId||'').toLowerCase())" in ui
    assert 'body[data-sentry-experience="chat"] #btnWorkspacePanelEdgeToggle' in css
    assert 'body[data-sentry-experience="chat"] .rightpanel' in css
    assert "agentAdminUseProviderModel" not in admin
    assert "Choose in Chat or Work" in admin


def test_session_update_persists_experience():
    source = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    update_block = source[source.index("parsed.path == \"/api/session/update\":"):source.index("parsed.path == \"/api/session/worktree/remove\":")]
    assert "if \"experience\" in body:" in update_block
    assert "new_exp = _validate_session_experience(body.get(\"experience\"))" in update_block
    assert "s.experience = new_exp" in update_block


def test_ui_experience_switch_is_in_place_and_preserves_messages():
    ui = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
    fn = ui[ui.index("async function selectExperience("):ui.index("function _topbarLoadedMessageCount()")]
    assert "await api('/api/session/update'" in fn
    assert "S.session.experience = next" in fn
    assert "options.forceNewSession" in fn


def test_target_selection_binds_native_workspace():
    integ = (ROOT / "static" / "sentry_integrations.js").read_text(encoding="utf-8")
    fn = integ[integ.index("async function selectSentryTarget("):integ.index("function targetLabel(")]
    assert "target.kind==='workspace'" in fn
    assert "S.session.native_workspace_id=target.workspace_id" in fn

