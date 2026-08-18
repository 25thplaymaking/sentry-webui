"""Tool activity must reach the browser instead of showing an endless "processing".

The Gateway already emits tool events -- its Hermes adapter maps
hermes.tool.started / hermes.tool.finished / hermes.tool.progress onto a
`tool.progress` RuntimeEvent and streams it. _translate_sentry_event then threw
every non-`message` event away, so the whole chain existed up to the last step
and the user saw nothing while the agent worked.

approval.required and needs.input were dropped by the same line, which is worse
than cosmetic: the agent would sit waiting for an answer the user was never
asked for, and the UI would show "processing" forever.
"""

import api.gateway_chat as gc


def ev(etype, summary="", **evidence):
    return {"type": etype, "summary": summary, "evidence": evidence or {}}


class TestToolEventsReachTheBrowser:
    def test_tool_progress_becomes_a_browser_tool_event(self):
        out = gc._translate_sentry_event(ev("tool.progress", "Checking services", tool="server_status"))
        assert out, "tool.progress must not be dropped"
        name, payload = out[0]
        assert name == "tool"
        assert payload["name"] == "server_status"

    def test_completed_tool_uses_the_complete_event(self):
        out = gc._translate_sentry_event(
            ev("tool.progress", "done", tool="server_status", status="completed")
        )
        name, payload = out[0]
        assert name == "tool_complete"
        assert payload["event_type"] == "tool.completed"

    def test_failed_tool_is_marked_as_an_error(self):
        out = gc._translate_sentry_event(
            ev("tool.progress", "boom", tool="server_action", status="error")
        )
        _, payload = out[0]
        assert payload["is_error"] is True

    def test_tool_name_falls_back_through_known_keys(self):
        for key in ("tool", "name", "function_name"):
            out = gc._translate_sentry_event(ev("tool.progress", "x", **{key: "the_tool"}))
            assert out[0][1]["name"] == "the_tool", key

    def test_unknown_evidence_shape_still_shows_something(self):
        """The evidence dict's shape is the runtime's, not ours. Even with no
        recognisable key the user must see activity rather than 'processing'."""
        out = gc._translate_sentry_event(ev("tool.progress", "Running a tool"))
        assert out
        assert out[0][1]["name"] or out[0][1]["preview"]

    def test_tool_call_id_is_passed_through_when_present(self):
        out = gc._translate_sentry_event(
            ev("tool.progress", "x", tool="t", tool_call_id="abc123")
        )
        assert out[0][1]["tid"] == "abc123"


class TestNothingRegressed:
    def test_message_still_becomes_a_token(self):
        assert gc._translate_sentry_event(ev("message", "hello")) == [("token", {"text": "hello"})]

    def test_empty_message_is_still_ignored(self):
        assert gc._translate_sentry_event(ev("message", "")) == []

    def test_control_events_are_still_left_to_the_caller(self):
        for etype in ("turn.completed", "error", "turn.failed"):
            assert gc._translate_sentry_event(ev(etype, "x")) == []

    def test_non_dict_is_ignored(self):
        assert gc._translate_sentry_event("nope") == []


class TestSilentWaitsAreSurfaced:
    def test_approval_required_is_not_silently_dropped(self):
        """Otherwise the agent waits for an approval the user never sees."""
        assert gc._translate_sentry_event(ev("approval.required", "Approve rm -rf?")) != []

    def test_needs_input_is_not_silently_dropped(self):
        assert gc._translate_sentry_event(ev("needs.input", "Which server?")) != []
