"""The WebUI half of identity-provider recovery: the four proxy routes.

`test_sentry_oidc_recovery.py` covers the ticket store underneath these. What is
asserted here is the part with the branches -- what the browser is told, what it
is never told, and what happens when the Gateway says no.

The single most important assertion in this file is
`test_success_keeps_the_recovery_code_out_of_the_redirect`. The obvious way to
write this flow is to bounce the browser back to the login page with the minted
code in the URL fragment, which would write a live credential into browser
history and into anything that reads the address bar. The code is parked
server-side instead, and that is a property worth failing a build over.
"""

import io
import json
from types import SimpleNamespace

import pytest

import api.gateway_chat as gateway_chat
import api.routes as routes
import api.sentry_gateway_auth as sga
import api.sentry_oidc_recovery as ticket_store
from api.sentry_gateway_auth import SentryAuthError


class _FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler the routes are given.

    Headers are kept as a list, not a dict: this flow sets more than one
    Set-Cookie on a single response, and a dict would quietly drop all but the
    last one -- hiding exactly the bug these tests exist to catch.
    """

    def __init__(self, body=None, cookie=""):
        encoded = json.dumps(body if body is not None else {}).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
            "Cookie": cookie,
        }
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
        self.rfile = io.BytesIO(encoded)
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = []

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers.append((key, str(value)))

    def end_headers(self):
        pass

    def header(self, name):
        for key, value in self.sent_headers:
            if key.lower() == name.lower():
                return value
        return None

    def cookies(self):
        return [value for key, value in self.sent_headers if key.lower() == "set-cookie"]

    def json(self):
        return json.loads(self.wfile.getvalue().decode() or "{}")


def _get(path, query="", cookie=""):
    handler = _FakeHandler(cookie=cookie)
    routes.handle_get(handler, SimpleNamespace(path=path, query=query))
    return handler


def _post(path, body, cookie=""):
    handler = _FakeHandler(body, cookie=cookie)
    routes.handle_post(handler, SimpleNamespace(path=path, query=""))
    return handler


@pytest.fixture
def sentry(monkeypatch):
    """Put the fork in the sentry dialect with a reachable Gateway URL."""
    monkeypatch.setattr(gateway_chat, "_gateway_dialect", lambda: "sentry")
    monkeypatch.setattr(gateway_chat, "_gateway_base_url", lambda: "http://gateway")


@pytest.fixture(autouse=True)
def _clean_tickets():
    ticket_store._tickets.clear()
    yield
    ticket_store._tickets.clear()


class TestDialectGate:
    """These routes only exist when this fork is fronting a Sentry Gateway."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/auth/sentry/oidc/status",
            "/api/auth/sentry/oidc/start",
            "/api/auth/sentry/oidc/callback",
        ],
    )
    def test_get_routes_are_absent_outside_the_sentry_dialect(self, monkeypatch, path):
        monkeypatch.setattr(gateway_chat, "_gateway_dialect", lambda: "hermes")
        assert _get(path).status == 404

    def test_complete_is_absent_outside_the_sentry_dialect(self, monkeypatch):
        monkeypatch.setattr(gateway_chat, "_gateway_dialect", lambda: "hermes")
        assert _post("/api/auth/sentry/oidc/complete", {"new_password": "x" * 12}).status == 404

    def test_an_unknown_subpath_is_not_a_wildcard(self, sentry):
        # The block is entered on a prefix match, so it has to close itself out.
        assert _get("/api/auth/sentry/oidc/anything-else").status == 404


class TestStatus:
    def test_reports_what_the_gateway_reports(self, sentry, monkeypatch):
        monkeypatch.setattr(
            sga, "oidc_recovery_status", lambda base, timeout=5.0: {
                "available": True, "display_name": "Google",
            }
        )
        handler = _get("/api/auth/sentry/oidc/status")
        assert handler.status == 200
        assert handler.json() == {"available": True, "display_name": "Google"}

    def test_an_unreachable_gateway_hides_the_button_rather_than_erroring(
        self, sentry, monkeypatch
    ):
        # This is read on every login page load. A Gateway that is down and one
        # with no provider configured are the same answer to the person here:
        # do not offer a door that cannot open.
        def _boom(base, timeout=5.0):
            raise SentryAuthError("gateway unreachable: refused")

        monkeypatch.setattr(sga, "oidc_recovery_status", _boom)
        handler = _get("/api/auth/sentry/oidc/status")
        assert handler.status == 200
        assert handler.json()["available"] is False


class TestStart:
    def test_redirects_to_the_provider_and_parks_the_flow_token(self, sentry, monkeypatch):
        monkeypatch.setattr(
            sga, "oidc_recovery_start", lambda base, timeout=15.0: {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1",
                "flow_token": "signed.flow.token",
            }
        )
        handler = _get("/api/auth/sentry/oidc/start")
        assert handler.status == 302
        assert handler.header("Location") == "https://accounts.google.com/o/oauth2/v2/auth?x=1"

        flow = [c for c in handler.cookies() if c.startswith(f"{ticket_store.FLOW_COOKIE}=")]
        assert len(flow) == 1
        assert "signed.flow.token" in flow[0]
        assert "HttpOnly" in flow[0]

    @pytest.mark.parametrize(
        "payload",
        [
            # A downgraded or attacker-named destination.
            {"authorization_url": "http://accounts.google.com/auth", "flow_token": "t"},
            # A relative Location would be resolved against this origin.
            {"authorization_url": "/login", "flow_token": "t"},
            # No verifier to come back with.
            {"authorization_url": "https://accounts.google.com/auth", "flow_token": ""},
        ],
    )
    def test_refuses_to_bounce_the_browser_somewhere_unverified(
        self, sentry, monkeypatch, payload
    ):
        monkeypatch.setattr(sga, "oidc_recovery_start", lambda base, timeout=15.0: payload)
        handler = _get("/api/auth/sentry/oidc/start")
        assert handler.status == 502
        assert handler.header("Location") is None

    def test_a_gateway_with_no_provider_configured_is_reported_not_redirected(
        self, sentry, monkeypatch
    ):
        def _absent(base, timeout=15.0):
            raise SentryAuthError("Not found.", status=404)

        monkeypatch.setattr(sga, "oidc_recovery_start", _absent)
        assert _get("/api/auth/sentry/oidc/start").status == 404


class TestCallback:
    def _flow_cookie(self, value="signed.flow.token"):
        return f"{ticket_store.FLOW_COOKIE}={value}"

    def test_success_keeps_the_recovery_code_out_of_the_redirect(self, sentry, monkeypatch):
        monkeypatch.setattr(
            sga, "oidc_recovery_callback",
            lambda base, code, state, flow, timeout=20.0: {
                "username": "bryce", "code": "AAAA-BBBB-CCCC", "expires_at": 0,
            },
        )
        handler = _get(
            "/api/auth/sentry/oidc/callback",
            query="code=provider-code&state=st",
            cookie=self._flow_cookie(),
        )
        assert handler.status == 302
        location = handler.header("Location")
        assert location == "/login#recovery-provider"

        # The minted code must not reach the browser by any route: not the URL,
        # not a readable cookie. Only the opaque ticket may cross.
        serialized = location + " " + " ".join(handler.cookies())
        assert "AAAA-BBBB-CCCC" not in serialized

        ticket = [c for c in handler.cookies() if c.startswith(f"{ticket_store.TICKET_COOKIE}=")]
        assert len(ticket) == 1
        assert "HttpOnly" in ticket[0]
        # ...and the code really is held server-side against it.
        assert list(ticket_store._tickets.values())[0][:2] == ("bryce", "AAAA-BBBB-CCCC")

    def test_the_flow_cookie_is_spent_even_when_the_exchange_succeeds(
        self, sentry, monkeypatch
    ):
        monkeypatch.setattr(
            sga, "oidc_recovery_callback",
            lambda base, code, state, flow, timeout=20.0: {
                "username": "bryce", "code": "AAAA-BBBB-CCCC", "expires_at": 0,
            },
        )
        handler = _get(
            "/api/auth/sentry/oidc/callback",
            query="code=provider-code&state=st",
            cookie=self._flow_cookie(),
        )
        cleared = [
            c for c in handler.cookies()
            if c.startswith(f"{ticket_store.FLOW_COOKIE}=") and "Max-Age=0" in c
        ]
        assert cleared, "a replayed callback must not get a second exchange"

    def test_a_refused_exchange_lands_on_the_failure_fragment(self, sentry, monkeypatch):
        def _refuse(base, code, state, flow, timeout=20.0):
            raise SentryAuthError("That sign-in could not be verified.", status=401)

        monkeypatch.setattr(sga, "oidc_recovery_callback", _refuse)
        handler = _get(
            "/api/auth/sentry/oidc/callback",
            query="code=provider-code&state=st",
            cookie=self._flow_cookie(),
        )
        assert handler.status == 302
        assert handler.header("Location") == "/login#recovery-provider-failed"
        assert not ticket_store._tickets

    @pytest.mark.parametrize(
        "query,cookie",
        [
            ("state=st", "flow"),                      # provider sent no code
            ("code=provider-code", "flow"),            # ...and no state
            ("code=provider-code&state=st", ""),       # no flow cookie: not our redirect
        ],
    )
    def test_an_incomplete_callback_never_reaches_the_gateway(
        self, sentry, monkeypatch, query, cookie
    ):
        def _unreached(*args, **kwargs):
            raise AssertionError("the Gateway must not be called for a malformed callback")

        monkeypatch.setattr(sga, "oidc_recovery_callback", _unreached)
        handler = _get(
            "/api/auth/sentry/oidc/callback",
            query=query,
            cookie=self._flow_cookie() if cookie else "",
        )
        assert handler.status == 302
        assert handler.header("Location") == "/login#recovery-provider-failed"

    def test_a_gateway_answer_missing_the_username_or_code_is_treated_as_failure(
        self, sentry, monkeypatch
    ):
        monkeypatch.setattr(
            sga, "oidc_recovery_callback",
            lambda base, code, state, flow, timeout=20.0: {"username": "bryce", "code": ""},
        )
        handler = _get(
            "/api/auth/sentry/oidc/callback",
            query="code=provider-code&state=st",
            cookie=self._flow_cookie(),
        )
        assert handler.header("Location") == "/login#recovery-provider-failed"
        assert not ticket_store._tickets


class TestComplete:
    def test_spends_the_ticket_and_sets_the_password_through_the_unchanged_path(
        self, sentry, monkeypatch
    ):
        seen = {}

        def _recover(base, username, code, new_password, timeout=15.0):
            seen.update(
                base=base, username=username, code=code, new_password=new_password
            )
            return {}

        monkeypatch.setattr(sga, "password_recover", _recover)
        ticket = ticket_store.issue_ticket("bryce", "AAAA-BBBB-CCCC")

        handler = _post(
            "/api/auth/sentry/oidc/complete",
            {"new_password": "a-long-enough-passphrase"},
            cookie=f"{ticket_store.TICKET_COOKIE}={ticket}",
        )
        assert handler.status == 200
        assert handler.json() == {"ok": True, "username": "bryce"}
        # The browser supplied only the new password; the username and the code
        # both came from the server-side ticket.
        assert seen == {
            "base": "http://gateway",
            "username": "bryce",
            "code": "AAAA-BBBB-CCCC",
            "new_password": "a-long-enough-passphrase",
        }

    def test_a_replayed_ticket_is_refused(self, sentry, monkeypatch):
        monkeypatch.setattr(
            sga, "password_recover",
            lambda base, username, code, new_password, timeout=15.0: {},
        )
        ticket = ticket_store.issue_ticket("bryce", "AAAA-BBBB-CCCC")
        cookie = f"{ticket_store.TICKET_COOKIE}={ticket}"

        assert _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "a-long-enough-passphrase"},
            cookie=cookie,
        ).status == 200
        assert _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "another-passphrase-x"},
            cookie=cookie,
        ).status == 401

    def test_no_ticket_at_all_is_refused_without_calling_the_gateway(
        self, sentry, monkeypatch
    ):
        def _unreached(*args, **kwargs):
            raise AssertionError("no ticket means there is nothing to spend")

        monkeypatch.setattr(sga, "password_recover", _unreached)
        handler = _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "a-long-enough-passphrase"}
        )
        assert handler.status == 401

    def test_the_ticket_cookie_is_cleared_on_both_outcomes(self, sentry, monkeypatch):
        monkeypatch.setattr(
            sga, "password_recover",
            lambda base, username, code, new_password, timeout=15.0: {},
        )
        ticket = ticket_store.issue_ticket("bryce", "AAAA-BBBB-CCCC")
        ok = _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "a-long-enough-passphrase"},
            cookie=f"{ticket_store.TICKET_COOKIE}={ticket}",
        )
        refused = _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "a-long-enough-passphrase"},
            cookie=f"{ticket_store.TICKET_COOKIE}=never-issued",
        )
        for handler in (ok, refused):
            assert any(
                c.startswith(f"{ticket_store.TICKET_COOKIE}=") and "Max-Age=0" in c
                for c in handler.cookies()
            )

    def test_a_gateway_rejection_is_surfaced_rather_than_swallowed(
        self, sentry, monkeypatch
    ):
        def _reject(base, username, code, new_password, timeout=15.0):
            raise SentryAuthError("Password does not meet the policy.", status=400)

        monkeypatch.setattr(sga, "password_recover", _reject)
        ticket = ticket_store.issue_ticket("bryce", "AAAA-BBBB-CCCC")
        handler = _post(
            "/api/auth/sentry/oidc/complete", {"new_password": "short"},
            cookie=f"{ticket_store.TICKET_COOKIE}={ticket}",
        )
        assert handler.status == 400
        assert "policy" in handler.json()["error"]
