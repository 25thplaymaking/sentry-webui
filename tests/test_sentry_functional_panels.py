"""Sentry panels expose real routes, guided intent, and safe empty states."""

from pathlib import Path

import api.routes as routes


ROOT = Path(__file__).resolve().parents[1]
PANELS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_every_primary_sentry_panel_has_purpose_steps_faq_and_a_real_demo_action():
    keys = (
        "chat",
        "tasks",
        "kanban",
        "skills",
        "memory",
        "workspaces",
        "profiles",
        "todos",
        "insights",
        "logs",
        "agentadmin",
        "settings",
    )
    for key in keys:
        start = PANELS.index(f"  {key}:{{")
        end = PANELS.find("\n  }", start)
        block = PANELS[start:end]
        assert "purpose:" in block, key
        assert "steps:[" in block, key
        assert "faq:[" in block, key
        assert "demo:" in block, key
    assert "syncPanelOrientation(nextPanel)" in PANELS
    assert "Guide & FAQ" in PANELS
    assert 'id="featureGuideDialog"' in HTML


def test_work_board_uses_authoritative_gateway_routes_for_all_visible_actions():
    assert "return _loadSentryWorkBoard(animate)" in PANELS
    assert "api('/api/kanban/board')" in PANELS
    assert "api('/api/kanban/tasks',{method:'POST'" in PANELS
    assert "api('/api/kanban/tasks/'+encodeURIComponent(workOrderId))" in PANELS
    assert "+encodeURIComponent(workOrderId)+'/transition'" in PANELS
    assert "valid assignment, workspace, and state transition" in HTML


def test_sentry_settings_hide_shared_container_controls_and_route_accounts_to_agent():
    assert "const allowed=new Set(['conversation','appearance','preferences','help'])" in PANELS
    assert "item.hidden=!allowed.has(item.dataset.settingsSection)" in PANELS
    assert "Manage linked accounts" in PANELS
    assert "DeepSeek remains the default assistant" in PANELS
    assert "settingsShowCliSessions" in PANELS
    assert "settingsLargeTextPasteAsAttachment" in PANELS
    assert "hide_composer_attach" in PANELS
    assert '[data-sentry-product="true"] .sentry-product-hidden' in CSS
    assert '[data-sentry-product="true"] #btnAttach' in CSS
    assert '[data-sentry-product="true"] #composerReasoningWrap' in CSS


def test_activity_projection_never_forwards_prompts_or_tool_arguments():
    lines = routes._sentry_activity_lines(
        [
            {
                "occurred_at": "2026-08-22T12:00:00Z",
                "status": "ok\r\nforged",
                "kind": "tool",
                "model": "deepseek-chat",
                "tool_name": "browser",
                "result_preview": "token sk-abcdefghijklmnopqrstuvwxyz123456\nfinished",
                "prompt": "private user prompt",
                "tool_args": {"command": "private command"},
            }
        ]
    )
    rendered = "\n".join(lines)
    assert "private user prompt" not in rendered
    assert "private command" not in rendered
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in rendered
    assert "\r" not in rendered and "\n" not in rendered
    assert "tool=browser" in rendered


def test_empty_states_name_the_next_working_action_instead_of_claiming_fake_data():
    assert "No live plan yet" in PANELS
    assert "No skills reported yet" in PANELS
    assert "No linked workspaces" in PANELS
    assert "No work orders yet" in PANELS
    assert "Start in Work" in PANELS
    assert "Open Agent" in PANELS
