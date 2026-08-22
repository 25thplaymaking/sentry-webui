"""The agent's pending-write queue and credential login, as the browser sees them.

Both surfaces were previously unreachable from the WebUI: Hermes keeps credential
login and write approval in its CLI, and this container never loads the agent.
The consequence was concrete — with `memory.write_approval: true` the agent
staged memory writes that nothing could ever approve, so they accumulated on disk
forever.

These tests pin the properties that keep the proxy honest:

  1. A failure is REPORTED, never rendered as "nothing pending". An empty queue
     and an unreachable one must not look the same — that is what let the gap
     stay invisible.
  2. A 501 (Hermes image predates the admin patch) is distinguishable from a
     transport failure, because the fixes are completely different.
  3. The pasted OAuth code reaches the Gateway verbatim, '#state' half included.
  4. Access tokens never come back to the browser.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from api import sentry_agent_admin as admin
from api.sentry_gateway_client import SentryGatewayError


class FakeHandler:
    pass


@pytest.fixture
def as_signed_in(monkeypatch):
    monkeypatch.setattr(admin, "_token_or_none", lambda handler: "tok")


@pytest.fixture
def as_signed_out(monkeypatch):
    monkeypatch.setattr(admin, "_token_or_none", lambda handler: None)


def stub_call(monkeypatch, result=None, error=None):
    """Replace the Gateway call, recording what it was asked to do."""
    calls = []

    def _fake(method, path, token, payload=None):
        calls.append((method, path, token, payload))
        if error is not None:
            return None, admin._unavailable(str(error), getattr(error, "status", 502))
        return result, None

    monkeypatch.setattr(admin, "_call", _fake)
    return calls


class TestFailuresAreReported:
    """An outage must never be indistinguishable from an empty queue."""

    def test_unreachable_gateway_is_not_an_empty_queue(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, error=SentryGatewayError("gateway unreachable", status=503))
        out = admin.pending_list(FakeHandler(), "memory")
        assert out["available"] is False
        assert out["items"] == []
        assert "unreachable" in out["error"]

    def test_empty_queue_is_available(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={"data": [], "approval_required": True})
        out = admin.pending_list(FakeHandler(), "memory")
        assert out["available"] is True
        assert out["items"] == []

    def test_signed_out_is_401_not_empty(self, monkeypatch, as_signed_out):
        out = admin.pending_list(FakeHandler(), "memory")
        assert out["available"] is False
        assert out["status"] == 401

    def test_unknown_subsystem_never_calls_the_gateway(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={})
        out = admin.pending_list(FakeHandler(), "bogus")
        assert out["available"] is False
        assert calls == []


class TestRebuildIsDistinguishable:
    """501 means 'rebuild the Hermes image', which no retry will fix."""

    def test_501_sets_needs_rebuild(self, monkeypatch, as_signed_in):
        stub_call(
            monkeypatch,
            error=SentryGatewayError("no Sentry admin surface", status=501),
        )
        out = admin.pending_list(FakeHandler(), "memory")
        assert out["needs_rebuild"] is True

    def test_transport_failure_does_not_set_needs_rebuild(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, error=SentryGatewayError("gateway unreachable", status=503))
        out = admin.pending_list(FakeHandler(), "memory")
        assert out["needs_rebuild"] is False


class TestPendingReview:
    def test_proposed_content_is_exposed_for_review(self, monkeypatch, as_signed_in):
        """A reviewer must see the write, not just a one-line summary of it."""
        stub_call(monkeypatch, result={
            "approval_required": True,
            "data": [{
                "id": "a1b2", "action": "add", "summary": "add to user profile: x",
                "origin": "assistant_tool", "created_at": 1.0,
                "payload": {"target": "user", "content": "the actual text",
                            "old_text": None},
            }],
        })
        item = admin.pending_list(FakeHandler(), "memory")["items"][0]
        assert item["content"] == "the actual text"
        assert item["target"] == "user"
        assert item["id"] == "a1b2"

    def test_approve_and_reject_hit_different_paths(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={"status": "ok"})
        admin.pending_decide(FakeHandler(), "memory", "a1b2", "approve")
        admin.pending_decide(FakeHandler(), "memory", "a1b2", "reject")
        assert calls[0][1].endswith("/memory/a1b2/approve")
        assert calls[1][1].endswith("/memory/a1b2/reject")

    def test_unknown_decision_never_calls_the_gateway(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={})
        out = admin.pending_decide(FakeHandler(), "memory", "a1b2", "delete")
        assert out["available"] is False
        assert calls == []

    def test_missing_pending_id_is_rejected(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={})
        out = admin.pending_decide(FakeHandler(), "memory", "", "approve")
        assert out["available"] is False
        assert calls == []


class TestCredentials:
    def test_old_runtime_error_is_turned_into_an_automatic_update_message(self):
        out = admin._unavailable("Rebuild the Hermes image on the server.", 501)
        assert out["needs_rebuild"] is True
        assert out["error"] == "Sentry is still enabling this feature. Try again shortly."
        assert "server" not in out["error"].lower()

    def test_unavailable_providers_never_tell_the_user_to_operate_the_server(
        self, monkeypatch, as_signed_in
    ):
        stub_call(monkeypatch, result={"data": [
            {"id": "anthropic", "authenticated": False,
             "name": "Anthropic", "oauth_capable": True,
             "oauth_over_http": True, "credentials": []},
            {"id": "qwen-oauth", "authenticated": False,
             "name": "Qwen OAuth", "oauth_capable": True,
             "oauth_over_http": False,
             "oauth_unavailable_reason": "Qwen OAuth is no longer offered.",
             "credentials": []},
        ]})
        providers = {p["id"]: p for p in admin.auth_providers(FakeHandler())["providers"]}
        assert providers["anthropic"]["browser_login"] is True
        assert providers["qwen-oauth"]["browser_login"] is False
        assert providers["qwen-oauth"]["unavailable_reason"].startswith("Qwen OAuth")
        assert "cli_command" not in providers["qwen-oauth"]
        assert "hermes auth" not in repr(providers)

    def test_browser_capable_providers_sort_first(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={"data": [
            {"id": "zzz-cli", "authenticated": False,
             "oauth_capable": True, "oauth_over_http": False, "credentials": []},
            {"id": "anthropic", "authenticated": False,
             "oauth_capable": True, "oauth_over_http": True, "credentials": []},
        ]})
        ids = [p["id"] for p in admin.auth_providers(FakeHandler())["providers"]]
        assert ids[0] == "anthropic"

    def test_access_tokens_are_never_returned_to_the_browser(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={"data": [{
            "id": "anthropic", "authenticated": True, "oauth_capable": True,
            "oauth_over_http": True,
            "credentials": [{"id": "c1", "label": "Claude Max",
                             "auth_type": "oauth", "expires_at_ms": 123,
                             "access_token": "SECRET-DO-NOT-LEAK"}],
        }]})
        out = admin.auth_providers(FakeHandler())
        assert "SECRET-DO-NOT-LEAK" not in repr(out)
        cred = out["providers"][0]["credentials"][0]
        assert set(cred) == {"id", "label", "auth_type", "expires_at_ms"}

    def test_connected_provider_exposes_only_selectable_route_metadata(
        self, monkeypatch, as_signed_in
    ):
        stub_call(monkeypatch, result={"data": [{
            "id": "openai-codex",
            "name": "OpenAI Codex",
            "authenticated": True,
            "oauth_capable": True,
            "oauth_over_http": True,
            "models": [
                {
                    "id": "chatgpt-plan/gpt-5.6-sol",
                    "model": "gpt-5.6-sol",
                    "api_key": "SECRET-MUST-NOT-LEAK",
                },
                {"id": "", "model": "invalid"},
            ],
            "route_error": None,
            "credentials": [],
        }]})

        provider = admin.auth_providers(FakeHandler())["providers"][0]

        assert provider["models"] == [{
            "id": "chatgpt-plan/gpt-5.6-sol",
            "model": "gpt-5.6-sol",
        }]
        assert provider["route_error"] is None
        assert "SECRET-MUST-NOT-LEAK" not in repr(provider)

    def test_completed_login_returns_identity_not_token(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={
            "provider": "anthropic",
            "credential": {"id": "c1", "label": "Claude Max"},
        })
        out = admin.auth_oauth_complete(
            FakeHandler(), {"flow_id": "f1", "code": "abc#def"}
        )
        assert out["credential"] == {"id": "c1", "label": "Claude Max"}


class TestOAuthCodeIntegrity:
    def test_pasted_code_reaches_the_gateway_verbatim(self, monkeypatch, as_signed_in):
        """The '#state' half is the CSRF binding — stripping it breaks the exchange."""
        calls = stub_call(monkeypatch, result={"provider": "anthropic", "credential": {}})
        admin.auth_oauth_complete(
            FakeHandler(), {"flow_id": "f1", "code": "thecode#thestate"}
        )
        assert calls[0][3]["code"] == "thecode#thestate"

    def test_incomplete_submission_never_calls_the_gateway(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={})
        assert admin.auth_oauth_complete(FakeHandler(), {"flow_id": "f1"})["available"] is False
        assert admin.auth_oauth_complete(FakeHandler(), {"code": "a#b"})["available"] is False
        assert calls == []

    def test_start_requires_a_provider(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={})
        out = admin.auth_oauth_start(FakeHandler(), {})
        assert out["available"] is False
        assert calls == []

    def test_start_returns_the_authorize_url(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={
            "flow_id": "f1", "provider": "anthropic",
            "authorize_url": "https://claude.ai/oauth/authorize?x=1",
            "expires_in": 900, "instructions": "paste the code",
        })
        out = admin.auth_oauth_start(FakeHandler(), {"provider": "anthropic"})
        assert out["authorize_url"].startswith("https://claude.ai/oauth/authorize")
        assert out["flow_id"] == "f1"

    def test_device_start_returns_code_and_poll_contract(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={
            "flow_id": "f2", "flow_kind": "device", "provider": "openai-codex",
            "status": "awaiting_user",
            "authorize_url": "https://auth.openai.com/codex/device",
            "user_code": "ABCD-EFGH", "poll_interval_seconds": 3,
        })
        out = admin.auth_oauth_start(FakeHandler(), {"provider": "openai-codex"})
        assert out["flow_kind"] == "device"
        assert out["user_code"] == "ABCD-EFGH"
        assert out["status"] == "awaiting_user"

    def test_status_and_cancel_use_fixed_flow_routes(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={
            "flow_id": "f1", "flow_kind": "device", "status": "awaiting_user",
        })
        status = admin.auth_oauth_status(FakeHandler(), "f1")
        cancelled = admin.auth_oauth_cancel(FakeHandler(), "f1")
        assert status["status"] == "awaiting_user"
        assert cancelled["ok"] is True
        assert calls[0][:2] == ("GET", "/api/agent/auth/oauth/f1")
        assert calls[1][:2] == ("DELETE", "/api/agent/auth/oauth/f1")


def test_agent_admin_ui_has_no_server_command_fallback():
    source = (Path(admin.__file__).parent.parent / "static" / "agent_admin.js").read_text(
        encoding="utf-8"
    )
    assert "Sign in on the server" not in source
    assert "hermes auth add" not in source
    assert "docker compose" not in source
    assert "agentAdminPollOAuth" in source
    assert "agentAdminCopyOAuthCode" in source
    assert "Open sign-in page" in source


def test_connected_subscription_routes_model_choice_to_chat_work_picker_without_changing_deepseek():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the subscription UI behavior test")
    script_path = Path(admin.__file__).parent.parent / "static" / "agent_admin.js"
    driver = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(script_path))}, 'utf8');
const nodes = {{
  agentAdminProviders: {{innerHTML: ''}},
  agentAdminOAuthBox: {{style: {{}}, innerHTML: ''}},
}};
let refreshed = 0;
let opened = 0;
let panels = [];
global.window = global;
global.document = {{getElementById: id => nodes[id] || null}};
global.S = {{session: {{model: 'deepseek-v4-flash', model_provider: 'sentry'}}}};
global.populateModelDropdown = async () => {{ refreshed += 1; }};
global.toggleModelDropdown = () => {{ opened += 1; }};
global.switchPanel = panel => panels.push(panel);
global.showToast = () => {{}};
vm.runInThisContext(source, {{filename: 'agent_admin.js'}});
const payload = {{available: true, providers: [{{
  id: 'openai-codex', name: 'OpenAI Codex', authenticated: true,
  browser_login: true, route_error: null, credentials: [],
  models: [
    {{id: 'chatgpt-plan/gpt-5.6-sol', model: 'gpt-5.6-sol'}},
    {{id: 'chatgpt-plan/gpt-5.6-terra', model: 'gpt-5.6-terra'}},
  ],
}}]}};
const html = _aaRenderProviders(payload);
(async () => {{
  const before = S.session.model;
  agentAdminOpenModelPicker();
  await Promise.resolve();
  process.stdout.write(JSON.stringify({{html, before, after: S.session.model, refreshed, opened, panels}}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    result = subprocess.run(
        [node, "-e", driver], capture_output=True, text=True, check=True
    )
    data = json.loads(result.stdout)
    assert data["before"] == "deepseek-v4-flash"
    assert data["after"] == "deepseek-v4-flash", "opening subscriptions must leave DeepSeek selected"
    assert "Choose in Chat or Work" in data["html"]
    assert "Use in chat" not in data["html"]
    assert "<select" not in data["html"]
    assert data["refreshed"] == 1
    assert data["opened"] == 1
    assert data["panels"] == ["chat"]


class TestLogout:
    def test_credential_selector_is_forwarded(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={"removed": 1})
        admin.auth_logout(FakeHandler(), "anthropic", "credential=c1")
        assert calls[0][1].endswith("?credential=c1")

    def test_absent_selector_removes_all(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={"removed": 2})
        admin.auth_logout(FakeHandler(), "anthropic", "")
        assert "?" not in calls[0][1]
