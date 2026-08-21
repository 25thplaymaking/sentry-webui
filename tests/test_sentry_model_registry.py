"""In the sentry dialect the picker shows only what the Gateway can route to.

Before this, /api/models fell through to get_available_models(), which
discovers by reading the AGENT's config.yaml -- a file the WebUI container
deliberately never mounts. Discovery therefore landed on a hardcoded
OpenRouter-style catalogue: a list of the world rather than of this
deployment. Every entry routed to the same place, and the one model that
could answer (local Qwen) was absent.

The invariant these tests pin is "no reachable model, no option". A menu that
repopulates itself from a static catalogue whenever the real registry is empty
or unreachable is the original defect wearing a different hat.
"""

import api.routes as routes


class TestEnvelopeShape:
    def test_aliases_become_pickable_models(self):
        env = routes._sentry_models_envelope(["qwen3.6-35b-local", "gpt-5.4"])
        assert env["groups"][0]["models"] == [
            {"id": "qwen3.6-35b-local", "label": "qwen3.6-35b-local"},
            {"id": "gpt-5.4", "label": "gpt-5.4"},
        ]

    def test_group_carries_provider_id_the_frontend_reads(self):
        env = routes._sentry_models_envelope(["gpt-5.4"])
        group = env["groups"][0]
        assert group["provider"] and group["provider_id"]

    def test_aliases_are_used_verbatim(self):
        """No relabeling: the operator's configured alias is what gets picked."""
        env = routes._sentry_models_envelope(["some-odd_alias.v2"])
        model = env["groups"][0]["models"][0]
        assert model["id"] == "some-odd_alias.v2"
        assert model["label"] == "some-odd_alias.v2"


class TestNoFallbackMenu:
    def test_no_models_yields_no_groups(self):
        env = routes._sentry_models_envelope([])
        assert env["groups"] == []

    def test_no_models_advertises_no_active_provider(self):
        env = routes._sentry_models_envelope([])
        assert env["active_provider"] is None

    def test_gateway_outage_is_reported_not_papered_over(self):
        env = routes._sentry_models_envelope([], unavailable=True)
        assert env["models_unavailable"] is True
        assert env["groups"] == []

    def test_healthy_empty_registry_is_not_flagged_as_an_outage(self):
        env = routes._sentry_models_envelope([])
        assert env["models_unavailable"] is False


class TestNoAssertedDefault:
    def test_default_model_is_not_invented(self):
        """The agent's own config decides the default; the picker must not guess."""
        env = routes._sentry_models_envelope(["qwen3.6-35b-local", "gpt-5.4"])
        assert env["default_model"] == ""
