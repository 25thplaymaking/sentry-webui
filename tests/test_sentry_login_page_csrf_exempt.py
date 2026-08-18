"""The login page's own POST endpoints must be CSRF-exempt.

Regression: the forced-password-change form (and lost-password recovery) are
rendered by static/login.js on the /login page. That page is NEVER given a
session CSRF token -- routes.py injects `__CSRF_TOKEN_JSON__` only into the
main app shell ("/" and "/session/..."), so login.js has no token to send and
posts with `Content-Type` alone.

With these paths missing from _csrf_exempt_path(), _check_csrf() therefore
failed with reason "token_mismatch" and the browser got

    403 {"error": "Session expired - reload the page"}

on a session that had just been created a few seconds earlier -- which reads to
the user as a broken/expired login rather than a blocked request.

CSRF exemption is safe for these two specifically, and for the same reason
/api/auth/login is already exempt: both are authenticated by a secret in the
REQUEST BODY that a cross-origin attacker cannot know or read back -- the
current password, or a recovery code issued out-of-band in Server Control.
"""

import api.routes as routes


# Every unsafe endpoint static/login.js posts to, and which of them the login
# page can actually supply a session CSRF token for (none of them -- the page
# never receives one).
LOGIN_PAGE_POST_ENDPOINTS = [
    "/api/auth/login",
    "/api/auth/password/change",
    "/api/auth/password/recover",
    "/api/auth/passkey/options",
    "/api/auth/passkey/login",
]


def test_every_login_page_endpoint_is_csrf_exempt():
    missing = [p for p in LOGIN_PAGE_POST_ENDPOINTS if not routes._csrf_exempt_path(p)]
    assert not missing, (
        "login.js posts to these from a page that is never given a CSRF token, "
        f"so they 403 with 'Session expired': {missing}"
    )


def test_password_change_is_csrf_exempt():
    assert routes._csrf_exempt_path("/api/auth/password/change")


def test_password_recover_is_csrf_exempt():
    assert routes._csrf_exempt_path("/api/auth/password/recover")


def test_exemption_is_not_blanket():
    """The exemption must stay a named allowlist, not a prefix match."""
    assert not routes._csrf_exempt_path("/api/auth/logout")
    assert not routes._csrf_exempt_path("/api/profiles")
    assert not routes._csrf_exempt_path("/api/auth/password/change/../../profiles")
