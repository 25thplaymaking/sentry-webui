"""Insights must report real usage, not a local store that is nearly empty.

_handle_insights reads LOCAL WebUI session data. Under the sentry dialect the
turns run in the Hermes container, so that store held almost nothing -- which is
exactly what the operator saw: 2 sessions under one model and 16 under
"unknown", with no tokens at all. The Gateway records real per-turn usage now,
so the sentry path asks it instead.

The "unknown" bucket is the specific thing these tests guard against: a label
that looks like a real model and silently absorbs everything unattributed.
"""

import api.routes as routes


GATEWAY_USAGE = {
    "days": 30,
    "by_model": [
        {"model": "qwen3.6-35b-local", "turns": 3,
         "input_tokens": "28471", "output_tokens": "67", "total_tokens": "28538"},
        {"model": None, "turns": 1,
         "input_tokens": "10", "output_tokens": "2", "total_tokens": "12"},
    ],
    "by_tool": [{"tool_name": "mcp__server_control__server_status", "calls": 2}],
}


class TestRealUsage:
    def test_models_and_tokens_come_through(self):
        env = routes._sentry_insights_envelope(GATEWAY_USAGE)
        first = env["by_model"][0]
        assert first["model"] == "qwen3.6-35b-local"
        assert first["input_tokens"] == 28471
        assert first["output_tokens"] == 67

    def test_bigint_strings_are_coerced_to_numbers(self):
        """Postgres bigint sums arrive as JSON strings; totals must still add."""
        env = routes._sentry_insights_envelope(GATEWAY_USAGE)
        assert env["totals"]["total_tokens"] == 28538 + 12
        assert isinstance(env["totals"]["input_tokens"], int)

    def test_tool_call_counts_are_carried(self):
        env = routes._sentry_insights_envelope(GATEWAY_USAGE)
        assert env["by_tool"][0]["calls"] == 2

    def test_turns_are_summed(self):
        assert routes._sentry_insights_envelope(GATEWAY_USAGE)["totals"]["turns"] == 4


class TestNoUnknownBucket:
    def test_a_null_model_is_named_unattributed_not_unknown(self):
        env = routes._sentry_insights_envelope(GATEWAY_USAGE)
        labels = [m["model"] for m in env["by_model"]]
        assert "unattributed" in labels
        assert "unknown" not in labels

    def test_unattributed_turns_are_not_silently_dropped(self):
        """Hiding them would understate usage; the point is that they are visible."""
        env = routes._sentry_insights_envelope(GATEWAY_USAGE)
        assert len(env["by_model"]) == 2


class TestDegradesHonestly:
    def test_gateway_outage_is_flagged_not_faked(self):
        env = routes._sentry_insights_envelope({}, unavailable=True)
        assert env["insights_unavailable"] is True
        assert env["by_model"] == []
        assert env["totals"]["total_tokens"] == 0

    def test_empty_usage_is_not_an_outage(self):
        env = routes._sentry_insights_envelope({"days": 30, "by_model": [], "by_tool": []})
        assert env["insights_unavailable"] is False

    def test_malformed_rows_are_skipped_rather_than_crashing(self):
        env = routes._sentry_insights_envelope(
            {"by_model": ["nope", {"model": "m", "turns": 1}], "by_tool": ["x"]}
        )
        assert [m["model"] for m in env["by_model"]] == ["m"]
        assert env["by_tool"] == []
