"""Sentry's Server Control-backed lost-password flow."""

import io
import json
import urllib.error
from types import SimpleNamespace

import api.routes as routes
import api.sentry_gateway_auth as sga


class _Resp:
    def __init__(self, raw=b""):
        self.raw = raw

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _FakeHandler:
    def __init__(self, body):
        encoded = json.dumps(body).encode()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
        self.rfile = io.BytesIO(encoded)
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


def _post(body):
    handler = _FakeHandler(body)
    routes.handle_post(handler, SimpleNamespace(path="/api/auth/password/recover"))
    return handler


class TestGatewayClient:
    def test_posts_the_code_and_new_password_to_the_gateway(self, monkeypatch):
        seen = {}

        def _open(request, timeout=None):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode())
            return _Resp()

        monkeypatch.setattr(sga.urllib.request, "urlopen", _open)
        assert sga.password_recover(
            "http://gateway", "bryce", "AAAA-BBBB-CCCC", "a-new-passphrase"
        ) == {}
        assert seen == {
            "url": "http://gateway/api/auth/password/recover",
            "body": {
                "username": "bryce",
                "code": "AAAA-BBBB-CCCC",
                "new_password": "a-new-passphrase",
            },
        }

    def test_maps_gateway_refusal_without_exposing_transport_details(self, monkeypatch):
        def _raise(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(json.dumps({"detail": "Recovery code is invalid or has expired."}).encode()),
            )

        monkeypatch.setattr(sga.urllib.request, "urlopen", _raise)
        try:
            sga.password_recover("http://gateway", "bryce", "bad", "a-new-passphrase")
            raise AssertionError("expected SentryAuthError")
        except sga.SentryAuthError as exc:
            assert exc.status == 400
            assert "invalid or has expired" in str(exc)


class TestWebUiRoute:
    def test_proxies_recovery_only_in_the_sentry_dialect(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        captured = {}

        def _recover(base, username, code, new_password, **kwargs):
            captured.update(
                base=base, username=username, code=code, new_password=new_password
            )

        monkeypatch.setattr(sga, "password_recover", _recover)
        handler = _post(
            {
                "username": "bryce",
                "code": "AAAA-BBBB-CCCC",
                "new_password": "a-new-passphrase",
            }
        )
        assert handler.status == 200
        assert handler.json() == {"ok": True}
        assert captured["username"] == "bryce"
        assert captured["code"] == "AAAA-BBBB-CCCC"

    def test_is_not_an_endpoint_on_shared_password_deployments(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        assert _post({}).status == 404


class TestLoginSurface:
    def test_recovery_control_is_only_rendered_for_sentry(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        assert 'id="forgot-password"' in routes._sentry_recovery_html()
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
        assert routes._sentry_recovery_html() == ""

    def test_template_has_one_recovery_insertion_point(self):
        assert routes._LOGIN_PAGE_HTML.count("{{SENTRY_RECOVERY_HTML}}") == 1
