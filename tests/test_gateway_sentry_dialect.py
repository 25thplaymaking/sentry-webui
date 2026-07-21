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
