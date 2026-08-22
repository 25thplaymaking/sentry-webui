"""Sentry integrations are persisted contracts and operational UI, not labels."""

from pathlib import Path

import api.gateway_chat as gateway_chat
import api.models as models
import api.routes as routes


ROOT = Path(__file__).resolve().parents[1]


def test_session_target_round_trips_and_is_strictly_validated():
    target = {
        "kind": "workspace",
        "node_id": "11111111-2222-3333-4444-555555555555",
        "node_name": "Bryce's PC",
        "workspace_id": "server-work",
    }
    session = models.Session(workspace=str(ROOT), sentry_target=target)
    assert session.compact()["sentry_target"] == target
    assert routes._validate_sentry_target(target) == target

    for invalid in (
        {"kind": "workspace", "node_id": "node", "workspace_id": r"C:\\Users\\Bryce"},
        {"kind": "service", "service_id": "minecraft", "name": "wrong", "extra": True},
        {"kind": "internet", "url": "https://example.com"},
    ):
        try:
            routes._validate_sentry_target(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe target accepted: {invalid}")


def test_native_codex_diff_is_forwarded_to_the_visible_inspector():
    patch = "diff --git a/app.py b/app.py\n-old\n+new"
    events = gateway_chat._translate_sentry_event(
        {
            "type": "tool.progress",
            "sessionId": "session-1",
            "evidence": {
                "native_method": "turn/diff/updated",
                "native": {"params": {"unifiedDiff": patch}},
            },
        }
    )
    assert events == [
        (
            "sentry_diff",
            {
                "session_id": "session-1",
                "diff": patch,
                "truncated": False,
                "source": "codex-live",
                "ts": events[0][1]["ts"],
            },
        )
    ]


def test_operational_surface_wires_sessions_targets_diffs_github_and_ide():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "sentry_integrations.js").read_text(encoding="utf-8")
    messages = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
    sessions = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")

    for element_id in (
        "linkedSessionHub",
        "providerSessionView",
        "sentryTargetChip",
        "sentryInspectorToggle",
        "sentryInspector",
        "sentryDiff",
        "sentryGithubContent",
        "sentryIntegrationsContent",
    ):
        assert f'id="{element_id}"' in html
    for action in ("sessionsSync", "sessionRead", "sessionWatch", "workspaceInspect", "openIde"):
        assert f"action:'{action}'" in js
    assert "/api/sentry/integrations/action" in js
    assert "node_id:workspace.node_id" in js
    assert 'onclick="toggleWorkspacePanel(false)"' in html
    assert "await selectExperience('work')" in js
    assert "Object.keys(S.session.sentry_target).length" in sessions
    assert "updateSentryLiveDiff" in messages
    assert "Provider website chats" in js
