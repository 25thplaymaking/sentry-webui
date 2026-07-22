"""Tests: per-client rate limiting keys off the real client behind a proxy.

Sentry is published over HTTPS through a proxy tier (Cloudflare Tunnel → the
`webui` container), so EVERY request arrives from the same socket peer — the
container network gateway. `_client_ip_for_rate_limit` previously returned that
raw peer, which collapsed every client on the internet into one bucket: a single
brute-forcer would trip the login throttle and lock out every legitimate user,
and no individual attacker could be isolated.

These tests pin the proxy-aware key on the same trust model the rest of the file
uses (`_onboarding_request_is_local`): forwarded headers count ONLY when the
operator opted in AND the un-spoofable socket peer is a trusted proxy, so a
direct public client cannot mint itself a fresh unthrottled bucket.
"""

import io


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default

    def get_all(self, key):
        return [v for k, v in self.items() if k.lower() == key.lower()]


class _Handler:
    def __init__(self, *, client_ip="8.8.8.8", headers=None):
        self.client_address = (client_ip, 12345)
        self.headers = _Headers(headers or {})
        self.rfile = io.BytesIO(b"{}")
        self.wfile = io.BytesIO()
        self.request = None


def _trusted_proxy(monkeypatch, cidrs="172.25.0.0/16"):
    monkeypatch.setenv("HERMES_WEBUI_TRUST_FORWARDED_FOR", "1")
    monkeypatch.setenv("HERMES_WEBUI_TRUSTED_PROXY_CIDRS", cidrs)


def _no_proxy_trust(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_TRUST_FORWARDED_FOR", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_TRUSTED_PROXY_CIDRS", raising=False)


# --------------------------------------------------------------------------
# The defect this fixes
# --------------------------------------------------------------------------

def test_distinct_clients_behind_one_proxy_get_distinct_keys(monkeypatch):
    """The regression: two internet clients must not share a bucket."""
    from api import routes

    _trusted_proxy(monkeypatch)
    a = _Handler(client_ip="172.25.0.6", headers={"X-Forwarded-For": "203.0.113.7"})
    b = _Handler(client_ip="172.25.0.6", headers={"X-Forwarded-For": "198.51.100.9"})

    key_a = routes._client_ip_for_rate_limit(a)
    key_b = routes._client_ip_for_rate_limit(b)

    assert key_a == "203.0.113.7"
    assert key_b == "198.51.100.9"
    assert key_a != key_b


# --------------------------------------------------------------------------
# Trust model — headers only count from a trusted peer, with the opt-in on
# --------------------------------------------------------------------------

def test_direct_public_client_cannot_spoof_its_key(monkeypatch):
    """A public peer sending XFF is keyed on its un-spoofable socket address."""
    from api import routes

    _trusted_proxy(monkeypatch)
    handler = _Handler(client_ip="8.8.8.8", headers={"X-Forwarded-For": "1.2.3.4"})
    assert routes._client_ip_for_rate_limit(handler) == "8.8.8.8"


def test_forwarded_header_ignored_without_the_opt_in(monkeypatch):
    from api import routes

    _no_proxy_trust(monkeypatch)
    handler = _Handler(client_ip="172.25.0.6", headers={"X-Forwarded-For": "203.0.113.7"})
    assert routes._client_ip_for_rate_limit(handler) == "172.25.0.6"


def test_untrusted_private_peer_is_not_a_proxy(monkeypatch):
    """A private peer outside the configured CIDRs cannot assert a client."""
    from api import routes

    _trusted_proxy(monkeypatch, cidrs="172.25.0.0/16")
    handler = _Handler(client_ip="10.9.9.9", headers={"X-Forwarded-For": "203.0.113.7"})
    assert routes._client_ip_for_rate_limit(handler) == "10.9.9.9"


def test_loopback_proxy_is_trusted_implicitly(monkeypatch):
    from api import routes

    monkeypatch.setenv("HERMES_WEBUI_TRUST_FORWARDED_FOR", "1")
    monkeypatch.delenv("HERMES_WEBUI_TRUSTED_PROXY_CIDRS", raising=False)
    handler = _Handler(client_ip="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.7"})
    assert routes._client_ip_for_rate_limit(handler) == "203.0.113.7"


# --------------------------------------------------------------------------
# Chain walking and failure modes
# --------------------------------------------------------------------------

def test_rightmost_untrusted_hop_wins(monkeypatch):
    """Hops appended by our own proxy tier are skipped; the real client wins."""
    from api import routes

    _trusted_proxy(monkeypatch)
    handler = _Handler(
        client_ip="172.25.0.6",
        headers={"X-Forwarded-For": "203.0.113.7, 172.25.0.4"},
    )
    assert routes._client_ip_for_rate_limit(handler) == "203.0.113.7"


def test_malformed_chain_fails_closed_into_one_shared_bucket(monkeypatch):
    """A malformed chain must not hand out a fresh unthrottled key each time."""
    from api import routes

    _trusted_proxy(monkeypatch)
    first = _Handler(client_ip="172.25.0.6", headers={"X-Forwarded-For": "not-an-ip"})
    second = _Handler(client_ip="172.25.0.6", headers={"X-Forwarded-For": ", ,"})

    assert routes._client_ip_for_rate_limit(first) == "forwarded-malformed"
    assert routes._client_ip_for_rate_limit(second) == "forwarded-malformed"


def test_x_real_ip_used_when_no_forwarded_for(monkeypatch):
    from api import routes

    _trusted_proxy(monkeypatch)
    handler = _Handler(client_ip="172.25.0.6", headers={"X-Real-IP": "203.0.113.7"})
    assert routes._client_ip_for_rate_limit(handler) == "203.0.113.7"


def test_trusted_proxy_speaking_for_itself_keys_on_the_peer(monkeypatch):
    """No forwarded headers at all → the proxy itself is the client."""
    from api import routes

    _trusted_proxy(monkeypatch)
    handler = _Handler(client_ip="172.25.0.6", headers={})
    assert routes._client_ip_for_rate_limit(handler) == "172.25.0.6"


def test_missing_client_address_is_not_a_wildcard_key(monkeypatch):
    from api import routes

    _no_proxy_trust(monkeypatch)
    handler = _Handler(client_ip="", headers={})
    assert routes._client_ip_for_rate_limit(handler) == "unknown"
