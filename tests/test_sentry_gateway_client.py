"""Fork -> Gateway proxy client: GET/POST parse, URL, and error mapping."""

import io
import json
import urllib.error

import pytest

import api.sentry_gateway_client as sgc


class _Resp:
    def __init__(self, body):
        self._b = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_json_parses(monkeypatch):
    monkeypatch.setattr(sgc.urllib.request, "urlopen", lambda req, timeout=None: _Resp([{"name": "s"}]))
    assert sgc.get_json("/api/skills", "tok", base_url="http://gw") == [{"name": "s"}]


def test_post_json_targets_right_url_with_bearer(monkeypatch):
    captured = {}

    def _open(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        return _Resp({"id": "1"})

    monkeypatch.setattr(sgc.urllib.request, "urlopen", _open)
    out = sgc.post_json("/api/cron", "tok", {"name": "n"}, base_url="http://gw")
    assert out == {"id": "1"}
    assert captured["url"] == "http://gw/api/cron"
    assert captured["auth"] == "Bearer tok"


def test_http_error_maps_status(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError("http://gw", 503, "x", {}, io.BytesIO(b""))

    monkeypatch.setattr(sgc.urllib.request, "urlopen", _raise)
    with pytest.raises(sgc.SentryGatewayError) as ei:
        sgc.get_json("/api/skills", "tok", base_url="http://gw")
    assert ei.value.status == 503


def test_empty_body_is_none(monkeypatch):
    monkeypatch.setattr(sgc.urllib.request, "urlopen", lambda req, timeout=None: _Resp(""))
    assert sgc.get_json("/api/x", "tok", base_url="http://gw") is None
