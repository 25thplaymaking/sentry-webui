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
    def test_cli_only_providers_get_no_browser_button(self, monkeypatch, as_signed_in):
        stub_call(monkeypatch, result={"data": [
            {"id": "anthropic", "authenticated": False,
             "oauth_capable": True, "oauth_over_http": True, "credentials": []},
            {"id": "openai-codex", "authenticated": False,
             "oauth_capable": True, "oauth_over_http": False, "credentials": []},
        ]})
        providers = {p["id"]: p for p in admin.auth_providers(FakeHandler())["providers"]}
        assert providers["anthropic"]["browser_login"] is True
        assert providers["anthropic"]["cli_command"] is None
        assert providers["openai-codex"]["browser_login"] is False
        # The CLI fallback is spelled out rather than leaving a dead button.
        assert "hermes auth add openai-codex" in providers["openai-codex"]["cli_command"]

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


class TestLogout:
    def test_credential_selector_is_forwarded(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={"removed": 1})
        admin.auth_logout(FakeHandler(), "anthropic", "credential=c1")
        assert calls[0][1].endswith("?credential=c1")

    def test_absent_selector_removes_all(self, monkeypatch, as_signed_in):
        calls = stub_call(monkeypatch, result={"removed": 2})
        admin.auth_logout(FakeHandler(), "anthropic", "")
        assert "?" not in calls[0][1]
