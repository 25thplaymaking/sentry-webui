"""Sentry gateway dialect: config gate + Sentry-SSE -> browser-event translation.

The browser expects the WebUI's own event names (incremental `token` deltas,
`done`, ...). These tests pin the mapping from the Sentry Gateway's
`/api/chat/turn` SSE (`{type,summary,...}`) onto those events without a live
gateway, since that translation is the load-bearing, easy-to-get-wrong part of
the chat repoint.
"""

import threading

import api.gateway_chat as gc


class TestDialect:
    def test_env_sentry_selects_sentry(self):
        assert gc._gateway_dialect(environ={"HERMES_WEBUI_GATEWAY_DIALECT": "sentry"}) == "sentry"

    def test_unset_defaults_to_hermes(self):
        assert gc._gateway_dialect(environ={}) == "hermes"

    def test_other_value_is_hermes(self):
        assert gc._gateway_dialect(environ={"HERMES_WEBUI_GATEWAY_DIALECT": "openai"}) == "hermes"

    def test_config_key_selects_sentry(self):
        assert gc._gateway_dialect({"webui_gateway_dialect": "sentry"}, environ={}) == "sentry"


class TestTranslate:
    def test_message_becomes_token(self):
        assert gc._translate_sentry_event({"type": "message", "summary": "hi"}) == [("token", {"text": "hi"})]

    def test_empty_message_is_dropped(self):
        assert gc._translate_sentry_event({"type": "message", "summary": ""}) == []

    def test_control_events_are_not_tokens(self):
        assert gc._translate_sentry_event({"type": "turn.completed", "summary": "x"}) == []
        assert gc._translate_sentry_event({"type": "error", "summary": "boom"}) == []

    def test_non_dict_is_empty(self):
        assert gc._translate_sentry_event("nope") == []


class _DummyResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _feed(lines):
    def _iter(resp, cancel_event):
        for line in lines:
            yield line if isinstance(line, bytes) else line.encode("utf-8")
    return _iter


def _run(monkeypatch, lines, **kwargs):
    monkeypatch.setattr(gc.urllib.request, "urlopen", lambda req, timeout=None: _DummyResp())
    monkeypatch.setattr(gc, "_iter_sse_lines_cancellable", _feed(lines))
    events = []
    return gc._run_sentry_turn_streaming(
        "sess", "hi", "sid", "http://gw", "key",
        put_gateway_event=lambda e, d: events.append((e, d)),
        cancel_event=threading.Event(),
        **kwargs,
    ), events


class TestStreaming:
    def test_incremental_messages_accumulate_and_stream_tokens(self, monkeypatch):
        (final_text, _usage), events = _run(monkeypatch, [
            'data: {"type":"message","summary":"He"}',
            'data: {"type":"message","summary":"llo"}',
            'data: {"type":"turn.completed","summary":""}',
            'data: [DONE]',
        ])
        assert final_text == "Hello"
        assert ("token", {"text": "He"}) in events
        assert ("token", {"text": "llo"}) in events

    def test_completion_only_summary_is_surfaced(self, monkeypatch):
        # A non-streaming agent that returns only a final turn.completed summary.
        (final_text, _usage), events = _run(monkeypatch, [
            'data: {"type":"turn.completed","summary":"the answer"}',
            'data: [DONE]',
        ])
        assert final_text == "the answer"
        assert ("token", {"text": "the answer"}) in events

    def test_terminal_error_raises(self, monkeypatch):
        import pytest
        with pytest.raises(RuntimeError, match="boom"):
            _run(monkeypatch, [
                'data: {"type":"error","summary":"boom"}',
                'data: [DONE]',
            ])


class _FakeHeaders:
    def __init__(self, cookie):
        self._c = cookie

    def get(self, key, default=""):
        return self._c if key == "Cookie" else default


class _FakeHandler:
    def __init__(self, cookie):
        self.headers = _FakeHeaders(cookie)


class TestSessionToken:
    def test_set_get_roundtrip(self):
        gc.set_sentry_session_token("s1", "tok")
        assert gc.get_sentry_session_token("s1") == "tok"
        gc.set_sentry_session_token("s1", None)
        assert gc.get_sentry_session_token("s1") is None

    def test_resolve_lifts_user_token_from_cookie(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        import api.auth as auth
        monkeypatch.setattr(auth, "get_session_info", lambda cv: {"gateway": {"access_token": "USERTOK"}})
        gc._resolve_sentry_token_for_request(_FakeHandler("hermes_session=abc.sig"), "sess-x")
        assert gc.get_sentry_session_token("sess-x") == "USERTOK"
        gc.set_sentry_session_token("sess-x", None)

    def test_resolve_is_noop_when_not_sentry(self, monkeypatch):
        monkeypatch.delenv("HERMES_WEBUI_GATEWAY_DIALECT", raising=False)
        gc._resolve_sentry_token_for_request(_FakeHandler("hermes_session=abc.sig"), "sess-y")
        assert gc.get_sentry_session_token("sess-y") is None


def _jwt_expiring_in(seconds):
    import base64
    import json as _j
    import time as _t
    payload = base64.urlsafe_b64encode(_j.dumps({"exp": _t.time() + seconds}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


class TestTokenRefresh:
    def test_far_from_expiry_is_not_refreshed(self, monkeypatch):
        import api.sentry_gateway_auth as sga
        calls = {"n": 0}
        monkeypatch.setattr(sga, "refresh", lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), {"access_token": "new"})[1])
        tok = _jwt_expiring_in(10000)
        assert gc._maybe_refresh_sentry_token("cookie", tok, "reftok") == tok
        assert calls["n"] == 0

    def test_near_expiry_refreshes_and_persists(self, monkeypatch):
        import api.sentry_gateway_auth as sga
        import api.auth as auth
        persisted = {}
        monkeypatch.setattr(sga, "refresh", lambda base, rt, **k: {"access_token": "NEWTOK", "refresh_token": "NEWREF"})
        monkeypatch.setattr(auth, "update_session_gateway", lambda cv, pair: persisted.update(pair) or True)
        out = gc._maybe_refresh_sentry_token("cookie", _jwt_expiring_in(10), "reftok")
        assert out == "NEWTOK"
        assert persisted.get("refresh_token") == "NEWREF"

    def test_no_refresh_token_keeps_current(self):
        assert gc._maybe_refresh_sentry_token("cookie", "tok", None) == "tok"


class TestAccessTokenFromHandler:
    def test_returns_token_in_sentry_mode(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        import api.auth as auth
        monkeypatch.setattr(auth, "get_session_info", lambda cv: {"gateway": {"access_token": "AT", "refresh_token": None}})
        assert gc.sentry_access_token_from_handler(_FakeHandler("hermes_session=x.y")) == "AT"

    def test_none_when_not_sentry(self, monkeypatch):
        monkeypatch.delenv("HERMES_WEBUI_GATEWAY_DIALECT", raising=False)
        assert gc.sentry_access_token_from_handler(_FakeHandler("hermes_session=x.y")) is None

    def test_none_when_no_cookie(self, monkeypatch):
        monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
        assert gc.sentry_access_token_from_handler(_FakeHandler("")) is None
