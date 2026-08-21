"""Thin client the fork's panel endpoints use to read/write the Sentry Gateway
as the logged-in user (sentry dialect only).

Each panel endpoint (Skills/Memory/Cron/Profiles/Kanban/inbox), instead of
reaching into an absent local agent package, proxies to the Gateway's
profile-scoped route with the caller's per-user bearer token. The Gateway base
URL is the same one chat uses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from api.gateway_chat import _gateway_base_url


class SentryGatewayError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _http_error_message(exc) -> str:
    """Best-effort human-readable message from a Gateway error response."""
    fallback = f"gateway {exc.code}"
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        return fallback
    if not raw:
        return fallback
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return fallback
    if isinstance(parsed, dict):
        detail = parsed.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return fallback


def _request(method: str, path: str, token: str, payload=None, *, base_url=None, timeout: float = 15.0):
    base = (base_url or _gateway_base_url()).rstrip("/")
    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Carry the Gateway's own message through. Without this every failure
        # collapses to "gateway <code>", which hides the distinction that
        # matters most here: 501 means "this Hermes image predates the admin
        # patch — rebuild it", not "something went wrong, try again".
        raise SentryGatewayError(
            _http_error_message(exc), status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise SentryGatewayError(f"gateway unreachable: {exc.reason}") from exc
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SentryGatewayError("gateway returned non-JSON") from exc


def get_json(path: str, token: str, *, base_url=None, timeout: float = 15.0):
    """GET a Gateway route as the user; returns the parsed JSON."""
    return _request("GET", path, token, base_url=base_url, timeout=timeout)


def post_json(path: str, token: str, payload: dict, *, base_url=None, timeout: float = 15.0):
    """POST to a Gateway route as the user; returns the parsed JSON."""
    return _request("POST", path, token, payload, base_url=base_url, timeout=timeout)


def delete_json(path: str, token: str, *, base_url=None, timeout: float = 15.0):
    """DELETE a Gateway route as the user; returns the parsed JSON."""
    return _request("DELETE", path, token, base_url=base_url, timeout=timeout)
