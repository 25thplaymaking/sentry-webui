"""The /api/auth/login route must honour the sentry-dialect door.

Companion to test_sentry_auth_door.py, which covers the policy helpers. These
cover the wiring: a correct shared password must NOT mint a session while the
sentry dialect is on, because such a session has no profile identity behind it.
"""

import io
import json
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


def _login(monkeypatch, *, dialect, password_ok=True):
    """POST a password login attempt and return (handler, session_was_created)."""
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", dialect)
    monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "verify_password", lambda _p: password_ok)

    created = []
    real_create = auth.create_session

    def _spy(*a, **kw):
        created.append((a, kw))
        return real_create(*a, **kw)

    monkeypatch.setattr(auth, "create_session", _spy)

    payload = json.dumps({"password": "the-shared-password"}).encode()
    handler = _FakeHandler(
        {"Content-Type": "application/json", "Content-Length": str(len(payload))},
        body=payload,
    )
    routes.handle_post(handler, SimpleNamespace(path="/api/auth/login"))
    return handler, bool(created)


def test_correct_password_is_refused_under_sentry_dialect(monkeypatch):
    handler, session_created = _login(monkeypatch, dialect="sentry")
    assert handler.status == 403
    assert not session_created, "a password login must not mint an identity-less session"


def test_refusal_tells_the_user_to_use_their_enrollment_code(monkeypatch):
    handler, _ = _login(monkeypatch, dialect="sentry")
    assert "enrollment code" in handler.wfile.getvalue().decode().lower()


def test_correct_password_still_works_on_hermes_dialect(monkeypatch):
    handler, session_created = _login(monkeypatch, dialect="hermes")
    assert handler.status == 200
    assert session_created
    assert json.loads(handler.wfile.getvalue().decode())["ok"] is True
