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
