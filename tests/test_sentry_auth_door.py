"""The sentry-dialect login door.

Under ``dialect=sentry`` identity comes from a per-user Gateway enrollment
token, not from the shared password. Two invariants matter, and getting either
wrong is a security incident:

1. The sentry dialect must itself COUNT as an auth method. Upstream
   ``is_auth_enabled()`` only knows about password/passkey/OIDC/trusted-header,
   so dropping ``HERMES_WEBUI_PASSWORD`` to force per-user login would silently
   turn authentication OFF and serve the portal to anyone.
2. With the dialect on, shared-password login must be REFUSED, so a session can
   never exist without a profile identity behind it (such a session logs in but
   then 401s on every Gateway call -- worse than being turned away).
"""

import api.auth as auth


def _isolate(monkeypatch, *, password=None, dialect="hermes", allow_password=None):
    """Strip every other auth method so the assertions are about the dialect."""
    monkeypatch.setattr(auth, "get_password_hash", lambda: password)
    monkeypatch.setattr(auth, "are_passkeys_enabled", lambda: False)
    monkeypatch.setattr(auth, "is_oidc_auth_enabled", lambda: False)
    monkeypatch.setattr(auth, "is_trusted_auth_enabled", lambda: False)
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", dialect)
    if allow_password is None:
        monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", allow_password)


def test_sentry_dialect_is_itself_an_auth_method(monkeypatch):
    """No password configured + sentry dialect => auth still ENABLED.

    This is the guard against the wide-open portal.
    """
    _isolate(monkeypatch, password=None, dialect="sentry")
    assert auth.is_sentry_auth_enabled() is True
    assert auth.is_auth_enabled() is True


def test_no_password_without_sentry_dialect_still_disables_auth(monkeypatch):
    """Regression guard: upstream behaviour is untouched for hermes deployments."""
    _isolate(monkeypatch, password=None, dialect="hermes")
    assert auth.is_sentry_auth_enabled() is False
    assert auth.is_auth_enabled() is False


def test_password_login_refused_under_sentry_dialect(monkeypatch):
    """Enrollment is the only door once the dialect is on."""
    _isolate(monkeypatch, password="hash", dialect="sentry")
    assert auth.password_login_allowed() is False


def test_password_login_allowed_on_hermes_dialect(monkeypatch):
    """Shared-password deployments keep working exactly as before."""
    _isolate(monkeypatch, password="hash", dialect="hermes")
    assert auth.password_login_allowed() is True


def test_escape_hatch_reenables_password_under_sentry_dialect(monkeypatch):
    """A deliberate opt-out exists so a misprovisioned team can't lock itself out."""
    _isolate(monkeypatch, password="hash", dialect="sentry", allow_password="1")
    assert auth.password_login_allowed() is True


def test_escape_hatch_needs_a_truthy_value(monkeypatch):
    _isolate(monkeypatch, password="hash", dialect="sentry", allow_password="0")
    assert auth.password_login_allowed() is False
