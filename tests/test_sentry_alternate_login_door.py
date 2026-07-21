"""Passkey and OIDC are non-enrollment doors, so the sentry dialect must shut them.

Companion to test_sentry_auth_door.py (policy) and test_sentry_login_route_door.py
(the password route). The password branch was closed first; passkey and OIDC were
left open, and they reach ``create_session()`` with no ``gateway=`` blob. A
session minted that way carries NO Sentry identity: the browser is signed in, the
shell renders, and then every Gateway-backed call 401s. That half-working state is
exactly what the password gate exists to prevent, so the same rule has to cover
every door that is not enrollment.

Neither method is configured on the live deployment, which is precisely why this
must be tested rather than observed.
"""

import io
from types import SimpleNamespace

import api.auth as auth
import api.routes as routes


class _FakeHandler:
    def __init__(self, headers=None, body=b"{}"):
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 12345)
        self.request = None  # _is_secure_context() probes this for a TLS peer cert
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass


def _dialect(monkeypatch, dialect, *, hatch=None):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", dialect)
    if hatch is None:
        monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", hatch)


def _spy_sessions(monkeypatch):
    """Record every create_session() call without minting a real cookie."""
    created = []
    monkeypatch.setattr(
        auth, "create_session", lambda *a, **kw: created.append((a, kw)) or "tok.sig"
    )
    return created


# ── Policy ──────────────────────────────────────────────────────────────────

def test_alternate_login_refused_under_sentry_dialect(monkeypatch):
    _dialect(monkeypatch, "sentry")
    assert auth.alternate_login_allowed() is False


def test_alternate_login_allowed_on_hermes_dialect(monkeypatch):
    _dialect(monkeypatch, "hermes")
    assert auth.alternate_login_allowed() is True


def test_escape_hatch_reopens_alternate_logins(monkeypatch):
    """One recovery knob for every non-enrollment door, so a misprovisioned
    passkey-only team is not locked out with no way back."""
    _dialect(monkeypatch, "sentry", hatch="1")
    assert auth.alternate_login_allowed() is True


# ── Passkey route ───────────────────────────────────────────────────────────

def test_passkey_login_is_refused_under_sentry_dialect(monkeypatch):
    _dialect(monkeypatch, "sentry")
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "_passkey_feature_flag_enabled", lambda: True)
    created = _spy_sessions(monkeypatch)

    handler = _FakeHandler()
    routes.handle_post(handler, SimpleNamespace(path="/api/auth/passkey/login"))

    assert handler.status == 403
    assert not created, "a passkey login must not mint an identity-less session"
    assert "enrollment code" in handler.wfile.getvalue().decode().lower()


def test_passkey_options_are_refused_under_sentry_dialect(monkeypatch):
    """Refuse at the first step too: handing out a WebAuthn challenge for a
    flow whose second step is closed is pure misdirection."""
    _dialect(monkeypatch, "sentry")
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "_passkey_feature_flag_enabled", lambda: True)

    handler = _FakeHandler()
    routes.handle_post(handler, SimpleNamespace(path="/api/auth/passkey/options"))
    assert handler.status == 403


def test_passkey_login_still_reaches_verification_on_hermes_dialect(monkeypatch):
    """Regression guard: shared-password deployments are untouched — the request
    gets as far as the real WebAuthn verifier (which rejects an empty body)."""
    _dialect(monkeypatch, "hermes")
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "_passkey_feature_flag_enabled", lambda: True)

    import api.passkeys as passkeys

    reached = []
    monkeypatch.setattr(
        passkeys, "finish_login", lambda body, handler: reached.append(True)
    )
    created = _spy_sessions(monkeypatch)

    handler = _FakeHandler()
    routes.handle_post(handler, SimpleNamespace(path="/api/auth/passkey/login"))

    assert reached, "the passkey verifier must still run for hermes deployments"
    assert handler.status == 200
    assert created


# ── OIDC routes ─────────────────────────────────────────────────────────────

def test_oidc_start_is_refused_under_sentry_dialect(monkeypatch):
    _dialect(monkeypatch, "sentry")
    handler = _FakeHandler()
    routes.handle_get(handler, SimpleNamespace(path="/api/auth/oidc/start", query=""))
    assert handler.status == 403
    assert "enrollment code" in handler.wfile.getvalue().decode().lower()


def test_oidc_callback_is_refused_under_sentry_dialect(monkeypatch):
    _dialect(monkeypatch, "sentry")
    created = _spy_sessions(monkeypatch)

    handler = _FakeHandler()
    routes.handle_get(
        handler,
        SimpleNamespace(path="/api/auth/oidc/callback", query="state=s&code=c"),
    )
    assert handler.status == 403
    assert not created, "an OIDC callback must not mint an identity-less session"


def test_oidc_start_is_untouched_on_hermes_dialect(monkeypatch):
    """Unconfigured OIDC still answers 404 (its own config error), not 403."""
    _dialect(monkeypatch, "hermes")
    handler = _FakeHandler()
    routes.handle_get(handler, SimpleNamespace(path="/api/auth/oidc/start", query=""))
    assert handler.status == 404


# ── Login page ──────────────────────────────────────────────────────────────

def test_passkey_button_is_dropped_when_alternate_login_is_refused(monkeypatch):
    _dialect(monkeypatch, "sentry")
    assert routes._passkey_login_html() == ""


def test_passkey_button_is_rendered_for_shared_password_deployments(monkeypatch):
    _dialect(monkeypatch, "hermes")
    assert 'id="passkey-login"' in routes._passkey_login_html()


def test_sso_link_is_dropped_when_alternate_login_is_refused(monkeypatch):
    _dialect(monkeypatch, "sentry")
    import api.auth_oidc as auth_oidc

    monkeypatch.setattr(auth_oidc, "is_oidc_enabled", lambda: True)
    assert routes._oidc_login_html(SimpleNamespace(query="")) == ""


def test_sso_link_is_rendered_on_hermes_dialect(monkeypatch):
    _dialect(monkeypatch, "hermes")
    import api.auth_oidc as auth_oidc

    monkeypatch.setattr(auth_oidc, "is_oidc_enabled", lambda: True)
    assert 'id="oidc-login"' in routes._oidc_login_html(SimpleNamespace(query=""))


def test_login_template_renders_the_passkey_button_through_the_helper():
    """Guard the wiring: a hard-coded button would bypass the gate entirely."""
    assert "{{PASSKEY_LOGIN_HTML}}" in routes._LOGIN_PAGE_HTML
    assert 'id="passkey-login"' not in routes._LOGIN_PAGE_HTML
