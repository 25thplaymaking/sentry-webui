"""Two residual sentry-dialect gaps closed.

1. Passkey REGISTRATION was ungated while passkey LOGIN was gated. Not a hole
   (registration requires an authenticated session), but under the sentry
   dialect it let a user mint credentials that can never sign them in — an
   invitation to lock yourself out of an account you think you secured.

2. `sentry_access_token_from_handler` read the COOKIE_NAME constant directly
   instead of `_resolve_cookie_name()`, which honours HERMES_WEBUI_COOKIE_NAME.
   Harmless while panels silently fell back to local data; now that they fail
   closed, setting that env var would 401 every panel for every user.
"""

import io
import json
from types import SimpleNamespace

import api.auth as auth
import api.gateway_chat as gateway_chat
import api.routes as routes


class _FakeHandler:
    def __init__(self, headers=None, body=b"{}"):
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, *_a):
        pass

    def end_headers(self):
        pass


def _sentry(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
    monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
    # Registration is gated behind the feature flag first; force it on so the
    # test exercises the dialect gate rather than the flag.
    monkeypatch.setattr(auth, "_passkey_feature_flag_enabled", lambda: True)


class TestPasskeyRegistrationGate:
    def _post(self, path):
        payload = json.dumps({}).encode()
        handler = _FakeHandler(
            {"Content-Type": "application/json", "Content-Length": str(len(payload))},
            body=payload,
        )
        routes.handle_post(handler, SimpleNamespace(path=path))
        return handler

    def test_register_options_is_refused_under_sentry_dialect(self, monkeypatch):
        _sentry(monkeypatch)
        handler = self._post("/api/auth/passkey/register/options")
        assert handler.status == 403
        assert "enrollment code" in handler.wfile.getvalue().decode().lower()

    def test_register_is_refused_under_sentry_dialect(self, monkeypatch):
        _sentry(monkeypatch)
        handler = self._post("/api/auth/passkey/register")
        assert handler.status == 403

    def test_registration_still_allowed_on_hermes_dialect(self, monkeypatch):
        """A shared-password deployment must be completely unaffected."""
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        monkeypatch.setattr(auth, "_passkey_feature_flag_enabled", lambda: True)
        handler = self._post("/api/auth/passkey/register/options")
        # Whatever it returns, it must NOT be our dialect refusal.
        assert handler.status != 403 or "enrollment code" not in handler.wfile.getvalue().decode().lower()


class TestCookieNameIsResolved:
    def test_sentry_token_honours_a_custom_cookie_name(self, monkeypatch):
        """With HERMES_WEBUI_COOKIE_NAME set, the token must still be found."""
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        monkeypatch.setenv("HERMES_WEBUI_COOKIE_NAME", "sentry_session")

        monkeypatch.setattr(
            auth, "get_session_info",
            lambda _v: {"gateway": {"access_token": "tok", "refresh_token": "r"}},
        )
        monkeypatch.setattr(
            gateway_chat, "_maybe_refresh_sentry_token",
            lambda _c, access, _r, **_k: access,
        )

        handler = _FakeHandler({"Cookie": "sentry_session=abc.def"})
        assert gateway_chat.sentry_access_token_from_handler(handler) == "tok"

    def test_default_cookie_name_still_works(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        monkeypatch.delenv("HERMES_WEBUI_COOKIE_NAME", raising=False)

        monkeypatch.setattr(
            auth, "get_session_info",
            lambda _v: {"gateway": {"access_token": "tok", "refresh_token": "r"}},
        )
        monkeypatch.setattr(
            gateway_chat, "_maybe_refresh_sentry_token",
            lambda _c, access, _r, **_k: access,
        )

        handler = _FakeHandler({"Cookie": f"{auth.COOKIE_NAME}=abc.def"})
        assert gateway_chat.sentry_access_token_from_handler(handler) == "tok"
