"""Health + restart must target the Sentry Gateway, not a local Hermes.

Observed live after the cutover: a banner reading "Hermes agent is not
responding — Gateway heartbeat failed" while the agent was visibly answering,
and pressing its Restart Service button produced
``FileNotFoundError: [Errno 2] No such file or directory: 'hermes'``.

Both are the same mistake: in the sentry dialect the WebUI has no local agent.
The Sentry Gateway exposes /health/ready and /health/live and NONE of the Hermes
probe paths (/health/detailed, /health, /v1/health all 404), and there is no
`hermes` binary in the WebUI container to restart.
"""

import io
import json
from types import SimpleNamespace

import api.agent_health as agent_health
import api.routes as routes


class _FakeHandler:
    def __init__(self):
        self.headers = {}
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
        self.rfile = io.BytesIO(b"{}")
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


def _hermes(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")


class TestProbePaths:
    def test_sentry_dialect_probes_the_gateway_readiness_path(self, monkeypatch):
        _sentry(monkeypatch)
        assert agent_health._remote_probe_paths() == ("/health/ready",)

    def test_hermes_dialect_keeps_the_original_paths(self, monkeypatch):
        _hermes(monkeypatch)
        assert agent_health._remote_probe_paths() == agent_health._REMOTE_PROBE_PATHS


class TestProbeResult:
    def test_healthy_gateway_is_not_reported_as_down(self, monkeypatch):
        """The false-alarm banner: /health/ready 200 must mean alive."""
        _sentry(monkeypatch)
        ready = json.dumps(
            {"status": "ready", "checks": {"runtime": {"name": "hermes", "healthy": True}}}
        ).encode()

        def _fake_probe(url, _timeout, api_key=None):
            # Only /health/ready exists on the Sentry Gateway.
            if url.endswith("/health/ready"):
                return True, 200, None, ready
            return False, 404, None, b""

        monkeypatch.setattr(agent_health, "_http_probe", _fake_probe)
        result = agent_health._run_remote_probe("http://gateway:8090")

        assert result["alive"] is True
        assert result["details"]["endpoint"].endswith("/health/ready")

    def test_genuinely_down_gateway_still_reports_down(self, monkeypatch):
        _sentry(monkeypatch)
        monkeypatch.setattr(
            agent_health, "_http_probe", lambda *_a, **_k: (False, None, "connection refused", b"")
        )
        result = agent_health._run_remote_probe("http://gateway:8090")
        assert result["alive"] is False


class TestRestart:
    def test_restart_is_refused_in_sentry_dialect_without_touching_local_hermes(self, monkeypatch):
        """No local `hermes` exists; the shared runtime is not a client's to restart."""
        _sentry(monkeypatch)
        called = []
        monkeypatch.setattr(
            routes, "restart_active_profile_gateway", lambda: called.append(1) or {}
        )

        handler = _FakeHandler()
        routes._handle_health_restart(handler)
        body = json.loads(handler.wfile.getvalue().decode())

        assert called == [], "must not shell out to a local hermes binary"
        assert body["ok"] is False
        assert "hermes" not in body["error"].lower() or "not" in body["error"].lower()
        assert handler.status == 501

    def test_hermes_dialect_still_restarts_the_local_gateway(self, monkeypatch):
        _hermes(monkeypatch)
        monkeypatch.setattr(
            routes, "restart_active_profile_gateway", lambda: {"status": "completed"}
        )
        handler = _FakeHandler()
        routes._handle_health_restart(handler)
        assert json.loads(handler.wfile.getvalue().decode())["ok"] is True
