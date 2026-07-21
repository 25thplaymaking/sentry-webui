"""Username + password sign-in in the sentry dialect.

Onboarding a teammate should be "here is a URL, a username and a password", not
a race against a five-minute enrollment code. The Gateway now mints its normal
token pair from a username and password; this covers the fork side.

Two things must not regress:

* the session created here has to be created EXACTLY as the enrollment path
  creates it -- ``auth_type="sentry"``, the token pair in ``gateway``, and no
  ``bound_profile`` (a Gateway profile UUID in that field 403s every request;
  see test_sentry_login_route_door.py).
* everything is inert unless the deployment runs the sentry dialect. A
  shared-password deployment must behave byte-identically.
"""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

import api.auth as auth
import api.routes as routes
import api.sentry_gateway_auth as sga


class _Resp:
    def __init__(self, body, *, raw=None):
        self._b = raw if raw is not None else json.dumps(body).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeHandler:
    def __init__(self, headers=None, body=b"{}"):
        self.headers = headers or {}
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
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

    def json(self):
        return json.loads(self.wfile.getvalue().decode() or "{}")


PAIR = {
    "access_token": "access-abc",
    "refresh_token": "refresh-abc",
    "device_id": "device-uuid",
    "profile_id": "gateway-profile-uuid",
    "must_change": False,
}


# ---------------------------------------------------------------- client ----


class TestGatewayClient:
    def test_password_login_posts_to_the_gateway_route(self, monkeypatch):
        seen = {}

        def _open(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode())
            return _Resp(PAIR)

        monkeypatch.setattr(sga.urllib.request, "urlopen", _open)
        out = sga.password_login("http://gw", "alice", "a-passphrase", "Browser")
        assert seen["url"] == "http://gw/api/auth/password/login"
        assert seen["body"] == {
            "username": "alice",
            "password": "a-passphrase",
            "device_name": "Browser",
        }
        assert out["access_token"] == "access-abc"

    def test_password_login_maps_a_refusal_to_autherror(self, monkeypatch):
        def _raise(req, timeout=None):
            raise urllib.error.HTTPError(
                "http://gw", 401, "Unauthorized", {},
                io.BytesIO(json.dumps({"detail": "Sign-in failed."}).encode()),
            )

        monkeypatch.setattr(sga.urllib.request, "urlopen", _raise)
        with pytest.raises(sga.SentryAuthError) as ei:
            sga.password_login("http://gw", "alice", "wrong", "Browser")
        assert ei.value.status == 401

    def test_password_change_sends_the_bearer_token(self, monkeypatch):
        seen = {}

        def _open(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data.decode())
            return _Resp(None, raw=b"")

        monkeypatch.setattr(sga.urllib.request, "urlopen", _open)
        sga.password_change("http://gw", "access-abc", "old-passphrase", "new-passphrase")
        assert seen["url"] == "http://gw/api/auth/password/change"
        assert seen["auth"] == "Bearer access-abc"
        assert seen["body"] == {
            "current_password": "old-passphrase",
            "new_password": "new-passphrase",
        }

    def test_password_change_tolerates_an_empty_204_body(self, monkeypatch):
        """The Gateway answers 204 with no body; parsing it as JSON would turn
        a success into 'gateway returned an unexpected response'."""
        monkeypatch.setattr(
            sga.urllib.request, "urlopen", lambda req, timeout=None: _Resp(None, raw=b"")
        )
        assert sga.password_change("http://gw", "t", "old-passphrase", "new-pass") == {}


# ----------------------------------------------------------- login route ----


def _post(handler_body, path="/api/auth/login"):
    payload = json.dumps(handler_body).encode()
    handler = _FakeHandler(
        {"Content-Type": "application/json", "Content-Length": str(len(payload))},
        body=payload,
    )
    routes.handle_post(handler, SimpleNamespace(path=path))
    return handler


def _sentry(monkeypatch, pair=None, *, error=None):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
    monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)

    def _login(base, username, password, device_name, **kw):
        if error is not None:
            raise error
        return dict(pair or PAIR)

    monkeypatch.setattr(sga, "password_login", _login)

    captured = {}
    real = auth.create_session

    def _spy(**kw):
        captured.update(kw)
        return real(**kw)

    monkeypatch.setattr(auth, "create_session", _spy)
    return captured


class TestLoginRoute:
    def test_username_and_password_sign_in(self, monkeypatch):
        _sentry(monkeypatch)
        handler = _post({"username": "alice", "password": "a-passphrase"})
        assert handler.status == 200
        assert handler.json()["ok"] is True

    def test_session_carries_the_gateway_pair(self, monkeypatch):
        captured = _sentry(monkeypatch)
        _post({"username": "alice", "password": "a-passphrase"})
        assert captured["auth_type"] == "sentry"
        assert captured["gateway"]["access_token"] == "access-abc"
        assert captured["gateway"]["profile_id"] == "gateway-profile-uuid"

    def test_session_does_not_bind_a_webui_profile(self, monkeypatch):
        """A Gateway profile UUID in bound_profile 403s every request. This is
        the same trap the enrollment path already has a test for."""
        captured = _sentry(monkeypatch)
        _post({"username": "alice", "password": "a-passphrase"})
        assert not captured.get("bound_profile")

    def test_wrong_password_is_refused_with_the_gateway_message(self, monkeypatch):
        _sentry(monkeypatch, error=sga.SentryAuthError("Sign-in failed.", status=401))
        handler = _post({"username": "alice", "password": "nope"})
        assert handler.status == 401
        assert "sign-in failed" in handler.wfile.getvalue().decode().lower()

    def test_wrong_password_mints_no_session(self, monkeypatch):
        captured = _sentry(monkeypatch, error=sga.SentryAuthError("no", status=401))
        _post({"username": "alice", "password": "nope"})
        assert captured == {}

    def test_must_change_is_reported_to_the_client(self, monkeypatch):
        _sentry(monkeypatch, pair=dict(PAIR, must_change=True))
        handler = _post({"username": "alice", "password": "a-passphrase"})
        assert handler.status == 200
        assert handler.json().get("must_change") is True

    def test_a_settled_password_does_not_report_must_change(self, monkeypatch):
        _sentry(monkeypatch)
        assert _post({"username": "alice", "password": "p"}).json().get("must_change") is False

    def test_enrollment_code_still_takes_precedence_and_works(self, monkeypatch):
        """Codes remain the device-pairing path. Adding a username field must
        not break the door the whole team currently uses."""
        _sentry(monkeypatch)
        monkeypatch.setattr(
            sga, "enroll_complete",
            lambda base, code, name: {
                "access_token": "e", "refresh_token": "r",
                "device_id": "d", "profile_id": "p",
            },
        )
        handler = _post({"enrollment_code": "AB-CD-EF", "device_name": "Browser"})
        assert handler.status == 200


class TestInertOutsideTheSentryDialect:
    def test_a_username_is_ignored_on_a_shared_password_deployment(self, monkeypatch):
        """The shared password decides, exactly as before -- the Gateway client
        must not even be consulted."""
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(auth, "verify_password", lambda _p: True)

        def _boom(*a, **kw):
            raise AssertionError("gateway password login must not run off-dialect")

        monkeypatch.setattr(sga, "password_login", _boom)
        handler = _post({"username": "alice", "password": "the-shared-password"})
        assert handler.status == 200

    def test_a_wrong_shared_password_is_still_refused_off_dialect(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(auth, "verify_password", lambda _p: False)
        assert _post({"username": "alice", "password": "wrong"}).status == 401

    def test_shared_password_is_still_refused_under_the_sentry_dialect(self, monkeypatch):
        """Without a username there is no per-user identity, so the old refusal
        stands: a session with no profile behind it 401s on every call."""
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)
        monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
        monkeypatch.setattr(auth, "verify_password", lambda _p: True)
        assert _post({"password": "the-shared-password"}).status == 403


# ---------------------------------------------------------- change route ----


class TestChangeRoute:
    def _authed(self, monkeypatch, *, token="access-abc", error=None):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
        import api.gateway_chat as gc

        monkeypatch.setattr(gc, "sentry_access_token_from_handler", lambda h: token)

        seen = {}

        def _change(base, access_token, current, new, **kw):
            if error is not None:
                raise error
            seen.update(
                {"token": access_token, "current": current, "new": new}
            )
            return {}

        monkeypatch.setattr(sga, "password_change", _change)
        return seen

    def test_forwards_the_change_with_the_session_token(self, monkeypatch):
        seen = self._authed(monkeypatch)
        handler = _post(
            {"current_password": "old-passphrase", "new_password": "new-passphrase"},
            path="/api/auth/password/change",
        )
        assert handler.status == 200
        assert seen == {
            "token": "access-abc",
            "current": "old-passphrase",
            "new": "new-passphrase",
        }

    def test_without_a_gateway_session_it_refuses(self, monkeypatch):
        self._authed(monkeypatch, token=None)
        handler = _post(
            {"current_password": "old-passphrase", "new_password": "new-passphrase"},
            path="/api/auth/password/change",
        )
        assert handler.status == 401

    def test_gateway_refusal_is_passed_through(self, monkeypatch):
        self._authed(
            monkeypatch,
            error=sga.SentryAuthError("Current password is incorrect.", status=403),
        )
        handler = _post(
            {"current_password": "wrong", "new_password": "new-passphrase"},
            path="/api/auth/password/change",
        )
        assert handler.status == 403
        assert "incorrect" in handler.wfile.getvalue().decode().lower()

    def test_route_is_absent_outside_the_sentry_dialect(self, monkeypatch):
        """A shared-password deployment has no Gateway credential to change;
        answering here at all would be advertising a door that goes nowhere."""
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
        handler = _post(
            {"current_password": "a", "new_password": "b"},
            path="/api/auth/password/change",
        )
        assert handler.status == 404


# ------------------------------------------------------------ login page ----


class TestLoginPage:
    def _sentry(self, monkeypatch, *, allow_password=False):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        if allow_password:
            monkeypatch.setenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", "1")
        else:
            monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)

    def test_username_and_password_fields_are_rendered(self, monkeypatch):
        self._sentry(monkeypatch)
        html = routes._sentry_credential_html()
        assert 'id="sentry-username"' in html
        assert 'id="sentry-password"' in html
        assert 'type="password"' in html

    def test_username_takes_the_autofocus(self, monkeypatch):
        """Autofocus lands on the first usable field, which is now the username."""
        self._sentry(monkeypatch)
        assert "autofocus" in routes._sentry_credential_html()
        assert "autofocus" not in routes._sentry_enroll_html()

    def test_nothing_is_rendered_off_dialect(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        assert routes._sentry_credential_html() == ""

    def test_the_shared_password_box_is_still_withheld(self, monkeypatch):
        """The per-user password is a different control from the shared one; the
        shared box would still be rejected, so it stays gone."""
        self._sentry(monkeypatch)
        assert routes._login_password_html() == ""

    def test_the_enrollment_field_is_still_offered(self, monkeypatch):
        """It is how a fresh device pairs and how someone with no password gets
        in, so it must not be removed."""
        self._sentry(monkeypatch)
        assert 'id="enroll-code"' in routes._sentry_enroll_html()

    def test_the_template_renders_the_credential_block(self, monkeypatch):
        assert "{{SENTRY_CREDENTIAL_HTML}}" in routes._LOGIN_PAGE_HTML


class TestLoginScript:
    """login.js has to actually send what the route now reads, and act on
    must_change. Source-level assertions, in the style of test_passkey_auth.py."""

    def _js(self):
        return open("static/login.js", encoding="utf-8").read()

    def test_it_reads_the_username_and_password_fields(self):
        js = self._js()
        assert "sentry-username" in js
        assert "sentry-password" in js

    def test_it_sends_a_username_in_the_payload(self):
        assert "payload.username" in self._js()

    def test_must_change_diverts_to_a_change_form(self):
        js = self._js()
        assert "data.must_change" in js
        assert "showChangeForm" in js

    def test_the_change_form_posts_to_the_change_route(self):
        assert "api/auth/password/change" in self._js()
