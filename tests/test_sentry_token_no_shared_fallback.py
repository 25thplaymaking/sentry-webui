"""Under the sentry dialect, a missing per-user token must never borrow a shared one.

DEFECT this pins: the sentry chat branch resolved its bearer as

    gateway_token or get_sentry_session_token(session_id) or api_key

where ``api_key`` is ``HERMES_WEBUI_GATEWAY_API_KEY`` -- one deployment-wide
credential shared by every user. Today the Sentry Gateway happens to reject it
(it is not a signed JWT), so the request fails closed by luck rather than by
design. The day that env var holds a value the Gateway accepts, every token-less
session chats as whatever profile that credential belongs to: a cross-user
identity leak whose only guard was an accident of token format.

The panel endpoints had a quieter version of the same shape: no token meant
falling through to the local WebUI container's own skills/memory/cron/profile
data, presenting one context's contents as if they were the signed-in user's.
"""

import io
import queue
from types import SimpleNamespace

import pytest

import api.gateway_chat as gc
import api.routes as routes


# ── Token resolution ────────────────────────────────────────────────────────

def test_explicit_request_token_wins(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_API_KEY", "shared-deployment-key")
    assert gc._sentry_turn_token("sess", "user-token") == "user-token"


def test_registered_session_token_is_used(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_API_KEY", "shared-deployment-key")
    gc.set_sentry_session_token("sess-registered", "worker-token")
    try:
        assert gc._sentry_turn_token("sess-registered", None) == "worker-token"
    finally:
        gc.set_sentry_session_token("sess-registered", None)


def test_shared_api_key_is_never_borrowed(monkeypatch):
    """The whole point: no per-user token means NO turn, not someone else's."""
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_API_KEY", "shared-deployment-key")
    gc.set_sentry_session_token("sess-empty", None)
    with pytest.raises(gc.SentryIdentityMissing) as excinfo:
        gc._sentry_turn_token("sess-empty", None)
    message = str(excinfo.value).lower()
    assert "sign in" in message
    assert "enrollment code" in message


# ── Chat wiring ─────────────────────────────────────────────────────────────

class _Sentinel(Exception):
    pass


def _drive_sentry_turn(monkeypatch, *, gateway_token):
    """Run the sentry chat branch far enough to see which bearer it resolves.

    Returns (tokens_seen, apperror_messages).
    """
    stream_id = "stream-under-test"
    session_id = "session-under-test"
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_API_KEY", "shared-deployment-key")

    session = SimpleNamespace(
        session_id=session_id,
        workspace="/workspace",
        profile=None,
        messages=[],
        context_messages=[],
        active_stream_id=None,  # keeps writeback/teardown a no-op
        save=lambda: None,
    )
    monkeypatch.setattr(gc, "get_session", lambda _sid: session)
    monkeypatch.setattr(gc, "register_active_run", lambda *a, **kw: None)
    monkeypatch.setattr(gc, "unregister_active_run", lambda *a, **kw: None)

    seen = []

    def _fake_turn(_sid, _msg, _stream, _base, token, **_kw):
        seen.append(token)
        raise _Sentinel("turn should not have been attempted")

    monkeypatch.setattr(gc, "_run_sentry_turn_streaming", _fake_turn)
    monkeypatch.setattr(
        gc,
        "_settle_gateway_terminal_error",
        lambda _sid, _stream, _ws, _m, _p, err: {"message": err},
    )

    q = queue.Queue()
    gc.STREAMS[stream_id] = q
    try:
        gc._run_gateway_chat_streaming(
            session_id, "hello", "gpt-x", "/workspace", stream_id,
            gateway_token=gateway_token,
        )
    finally:
        gc.STREAMS.pop(stream_id, None)

    errors = []
    while not q.empty():
        item = q.get_nowait()
        if item[0] == "apperror":
            errors.append(str(item[1]))
    return seen, errors


def test_tokenless_sentry_turn_errors_instead_of_using_the_shared_key(monkeypatch):
    seen, errors = _drive_sentry_turn(monkeypatch, gateway_token=None)
    assert seen == [], f"the turn must not be attempted at all, got bearer {seen}"
    assert errors, "the failure must reach the UI as an apperror"
    joined = " ".join(errors).lower()
    assert "sign in" in joined and "enrollment code" in joined


def test_sentry_turn_uses_the_callers_own_token(monkeypatch):
    seen, _ = _drive_sentry_turn(monkeypatch, gateway_token="caller-token")
    assert seen == ["caller-token"]


# ── Panel endpoints ─────────────────────────────────────────────────────────

class _FakeHandler:
    def __init__(self):
        self.headers = {}
        self.client_address = ("127.0.0.1", 12345)
        self.request = None
        self.rfile = io.BytesIO(b"{}")
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass


_PANELS = [
    "/api/skills",
    "/api/memory",
    "/api/crons",
    "/api/profiles",
    "/api/agent-messages",
    "/api/kanban/board",
]


@pytest.mark.parametrize("path", _PANELS)
def test_panels_refuse_instead_of_serving_local_data(monkeypatch, path):
    """No Sentry identity => an error, not this container's own contents."""
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
    monkeypatch.setattr(gc, "sentry_access_token_from_handler", lambda _h: None)

    handler = _FakeHandler()
    routes.handle_get(handler, SimpleNamespace(path=path, query=""))

    assert handler.status == 401, f"{path} served a response without an identity"
    assert "enrollment code" in handler.wfile.getvalue().decode().lower()


@pytest.mark.parametrize("path", _PANELS)
def test_panels_are_untouched_on_hermes_dialect(monkeypatch, path):
    """Regression guard: shared-password deployments still take the local path.

    Some local handlers need the ``agent`` package, which this venv does not
    install -- an exception escaping from there is still proof the sentry gate
    did not fire, because the gate answers 401 and returns.
    """
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")

    handler = _FakeHandler()
    try:
        routes.handle_get(handler, SimpleNamespace(path=path, query=""))
    except Exception:
        pass

    assert handler.status != 401
