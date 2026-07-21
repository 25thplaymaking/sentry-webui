"""Sentry Gateway auth client: enroll/refresh happy paths + error mapping."""

import io
import json
import urllib.error

import pytest

import api.sentry_gateway_auth as sga


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_enroll_complete_parses_token_pair(monkeypatch):
    monkeypatch.setattr(
        sga.urllib.request, "urlopen",
        lambda req, timeout=None: _Resp(
            {"access_token": "a", "refresh_token": "r", "device_id": "d", "profile_id": "p"}
        ),
    )
    out = sga.enroll_complete("http://gw", "CODE", "Browser")
    assert out["access_token"] == "a"
    assert out["profile_id"] == "p"


def test_refresh_parses_rotated_pair(monkeypatch):
    monkeypatch.setattr(
        sga.urllib.request, "urlopen",
        lambda req, timeout=None: _Resp(
            {"access_token": "a2", "refresh_token": "r2", "device_id": "d", "profile_id": "p"}
        ),
    )
    out = sga.refresh("http://gw", "r")
    assert out["refresh_token"] == "r2"


def test_http_error_becomes_autherror_with_detail(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError(
            "http://gw", 400, "Bad", {},
            io.BytesIO(json.dumps({"detail": "Enrollment code is invalid or has expired."}).encode()),
        )

    monkeypatch.setattr(sga.urllib.request, "urlopen", _raise)
    with pytest.raises(sga.SentryAuthError) as ei:
        sga.enroll_complete("http://gw", "BAD", "B")
    assert ei.value.status == 400
    assert "invalid" in str(ei.value).lower()


def test_unreachable_becomes_autherror(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(sga.urllib.request, "urlopen", _raise)
    with pytest.raises(sga.SentryAuthError):
        sga.refresh("http://gw", "r")


def _mk_jwt(exp):
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"


def test_jwt_exp_reads_exp_without_verifying():
    assert sga.jwt_exp(_mk_jwt(1234567890)) == 1234567890.0


def test_jwt_exp_garbage_is_none():
    assert sga.jwt_exp("not-a-jwt") is None
    assert sga.jwt_exp(None) is None
    assert sga.jwt_exp("a.b.c") is None
