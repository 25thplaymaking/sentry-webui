"""Identity-provider account recovery, and the auth gate in front of it.

The gate tests matter more than they look. Every existing recovery test drives
``routes.handle_post`` directly, which skips ``check_auth`` -- so a recovery
endpoint could be, and was, unreachable to the only people who ever need it
while its handler tests stayed green.
"""

import time

import api.auth as auth
import api.sentry_oidc_recovery as recovery


class TestRecoveryPathsAreReachableWhileSignedOut:
    """``check_auth`` runs before dispatch (server.py), so a recovery route left
    out of PUBLIC_PATHS answers 401 to exactly the locked-out user it exists
    for. The handler never runs, and no handler-level test can see it."""

    def test_sentry_recovery_paths_are_public(self):
        for path in (
            "/api/auth/password/recover",
            "/api/auth/sentry/oidc/status",
            "/api/auth/sentry/oidc/start",
            "/api/auth/sentry/oidc/callback",
            "/api/auth/sentry/oidc/complete",
        ):
            assert path in auth.PUBLIC_PATHS, f"{path} is unreachable while signed out"

    def test_password_change_stays_private(self):
        # Changing a password from Settings requires the session it is changing.
        assert "/api/auth/password/change" not in auth.PUBLIC_PATHS


class TestRecoveryTickets:
    """The minted recovery code is parked server-side rather than handed to the
    browser, so the ticket is the thing that must not be reusable."""

    def test_ticket_redeems_exactly_once(self):
        ticket = recovery.issue_ticket("bryce", "ABCD-EF01-2345")

        assert recovery.consume_ticket(ticket) == ("bryce", "ABCD-EF01-2345")
        assert recovery.consume_ticket(ticket) is None

    def test_unknown_or_missing_ticket_is_refused(self):
        assert recovery.consume_ticket(None) is None
        assert recovery.consume_ticket("") is None
        assert recovery.consume_ticket("never-issued") is None

    def test_expired_ticket_is_refused(self, monkeypatch):
        ticket = recovery.issue_ticket("bryce", "ABCD-EF01-2345")

        issued_at = time.time()
        monkeypatch.setattr(
            recovery.time, "time", lambda: issued_at + recovery.TICKET_TTL_SECONDS + 1
        )
        assert recovery.consume_ticket(ticket) is None

    def test_tickets_are_unguessable_and_distinct(self):
        first = recovery.issue_ticket("bryce", "code-one")
        second = recovery.issue_ticket("bryce", "code-two")

        assert first != second
        assert len(first) >= 32


class TestRecoveryCookies:
    def test_cookies_are_httponly_and_lax(self):
        header = recovery.set_cookie_header(recovery.TICKET_COOKIE, "value", secure=True)

        assert "HttpOnly" in header
        # Lax, not Strict: the provider redirect is a cross-site top-level
        # navigation and a Strict cookie would simply not be sent with it.
        assert "SameSite=Lax" in header
        assert "Secure" in header
        assert f"Max-Age={recovery.TICKET_TTL_SECONDS}" in header

    def test_insecure_context_omits_the_secure_flag(self):
        # The portal is reached over plain http on a loopback SSH forward; a
        # Secure cookie there would simply never be stored.
        header = recovery.set_cookie_header(recovery.TICKET_COOKIE, "value", secure=False)

        assert "Secure" not in header

    def test_clearing_expires_the_cookie(self):
        header = recovery.clear_cookie_header(recovery.FLOW_COOKIE)

        assert "Max-Age=0" in header

    def test_read_cookie_tolerates_missing_and_malformed_headers(self):
        assert recovery.read_cookie(_FakeHeaders(None), recovery.FLOW_COOKIE) is None
        assert recovery.read_cookie(_FakeHeaders(""), recovery.FLOW_COOKIE) is None
        assert (
            recovery.read_cookie(_FakeHeaders("sentry_oidc_flow=abc123"), recovery.FLOW_COOKIE)
            == "abc123"
        )


class _FakeHeaders:
    def __init__(self, cookie):
        self.headers = {} if cookie is None else {"Cookie": cookie}
