"""WebUI routes for the agent's own credentials and pending writes.

These proxy the Gateway's ``/api/agent/*`` surface, which in turn proxies the
admin surface patched into Hermes. The chain exists because Hermes keeps
credential login and pending-write approval in its CLI, and this container never
loads the agent — so before this, logging a Claude subscription into the harness
needed a TTY on the server, and memory writes the agent staged for review
accumulated on disk with nothing able to approve them.

**Not to be confused with ``/api/memory``**, which is the caller's own
Gateway-stored memory. The memory here is the *agent's* memory inside Hermes.

Failures are reported, never papered over: a 501 means the Hermes image predates
the admin patch and must be rebuilt, which is a completely different fix from a
transport blip, so the two must not render identically.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, quote

# Subsystems the agent can stage writes for. Validated here so a typo never
# becomes a Gateway round trip.
_SUBSYSTEMS = ("memory", "skills")


def _unavailable(message: str, status: int) -> dict:
    """Envelope for a failed admin-surface call.

    ``needs_rebuild`` lets the UI say the useful thing ("rebuild the Hermes
    image") instead of a generic retry prompt.
    """
    return {
        "available": False,
        "error": message,
        "status": status,
        "needs_rebuild": status == 501,
        "items": [],
        "providers": [],
    }


def _token_or_none(handler):
    from api.gateway_chat import sentry_access_token_from_handler

    return sentry_access_token_from_handler(handler)


def _call(method: str, path: str, token: str, payload=None):
    """Call the Gateway, normalising errors into (data, error_envelope)."""
    from api.sentry_gateway_client import (
        SentryGatewayError,
        delete_json,
        get_json,
        post_json,
    )

    try:
        if method == "GET":
            return get_json(path, token), None
        if method == "POST":
            return post_json(path, token, payload or {}), None
        if method == "DELETE":
            return delete_json(path, token), None
    except SentryGatewayError as exc:
        return None, _unavailable(str(exc), getattr(exc, "status", None) or 502)
    raise ValueError(f"unsupported method {method}")


# ---------------------------------------------------------------------------
# Pending agent writes
# ---------------------------------------------------------------------------


def pending_list(handler, subsystem: str) -> dict:
    """The agent's staged writes awaiting a decision."""
    if subsystem not in _SUBSYSTEMS:
        return _unavailable(f"unknown subsystem '{subsystem}'", 404)
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)

    data, err = _call("GET", f"/api/agent/pending/{quote(subsystem)}", token)
    if err:
        return err

    data = data or {}
    items = []
    for record in data.get("data") or []:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload") or {}
        items.append(
            {
                "id": record.get("id"),
                "action": record.get("action"),
                "summary": record.get("summary"),
                "origin": record.get("origin"),
                "created_at": record.get("created_at"),
                # The proposed content, so a reviewer can judge the write rather
                # than approving a one-line summary of it.
                "target": payload.get("target"),
                "content": payload.get("content"),
                "old_text": payload.get("old_text"),
            }
        )
    return {
        "available": True,
        "subsystem": subsystem,
        "approval_required": bool(data.get("approval_required")),
        "items": items,
    }


def pending_decide(handler, subsystem: str, pending_id: str, decision: str) -> dict:
    """Approve (apply) or reject (discard) one staged write."""
    if subsystem not in _SUBSYSTEMS:
        return _unavailable(f"unknown subsystem '{subsystem}'", 404)
    if decision not in ("approve", "reject"):
        return _unavailable(f"unknown decision '{decision}'", 400)
    if not pending_id:
        return _unavailable("pending id is required", 400)
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)

    data, err = _call(
        "POST",
        f"/api/agent/pending/{quote(subsystem)}/{quote(pending_id)}/{decision}",
        token,
    )
    if err:
        return err
    return {"available": True, "ok": True, **(data or {})}


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def auth_providers(handler) -> dict:
    """Credential providers, and which this profile is signed into.

    Only providers with ``oauth_over_http`` can be logged in from the browser.
    The rest are CLI-only, and are reported as such rather than shown with a
    button that leads nowhere.
    """
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)

    data, err = _call("GET", "/api/agent/auth/providers", token)
    if err:
        return err

    providers = []
    for entry in (data or {}).get("data") or []:
        if not isinstance(entry, dict):
            continue
        provider_id = entry.get("id")
        providers.append(
            {
                "id": provider_id,
                "authenticated": bool(entry.get("authenticated")),
                "oauth_capable": bool(entry.get("oauth_capable")),
                "browser_login": bool(entry.get("oauth_over_http")),
                "credentials": [
                    {
                        "id": cred.get("id"),
                        "label": cred.get("label"),
                        "auth_type": cred.get("auth_type"),
                        "expires_at_ms": cred.get("expires_at_ms"),
                    }
                    for cred in entry.get("credentials") or []
                    if isinstance(cred, dict)
                ],
                "cli_command": (
                    None
                    if entry.get("oauth_over_http")
                    else f"hermes auth add {provider_id} --type oauth"
                    if entry.get("oauth_capable")
                    else None
                ),
            }
        )
    providers.sort(key=lambda p: (not p["browser_login"], not p["authenticated"], p["id"] or ""))
    return {"available": True, "providers": providers}


def auth_oauth_start(handler, body: dict) -> dict:
    """Begin a browser OAuth login and hand back the URL to open."""
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)
    provider = str((body or {}).get("provider") or "").strip()
    if not provider:
        return _unavailable("provider is required", 400)

    data, err = _call(
        "POST", "/api/agent/auth/oauth/start", token, {"provider": provider}
    )
    if err:
        return err
    data = data or {}
    return {
        "available": True,
        "flow_id": data.get("flow_id"),
        "provider": data.get("provider", provider),
        "authorize_url": data.get("authorize_url"),
        "expires_in": data.get("expires_in"),
        "instructions": data.get("instructions"),
    }


def auth_oauth_complete(handler, body: dict) -> dict:
    """Finish a login with the code pasted from the provider's callback page."""
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)
    body = body or {}
    flow_id = str(body.get("flow_id") or "").strip()
    # Sent verbatim: the provider shows "<code>#<state>" and the state half is
    # the CSRF binding, so splitting or trimming it here would break the
    # exchange (or silently weaken it).
    code = str(body.get("code") or "").strip()
    if not flow_id or not code:
        return _unavailable("flow_id and code are required", 400)

    payload = {"flow_id": flow_id, "code": code}
    label = str(body.get("label") or "").strip()
    if label:
        payload["label"] = label

    data, err = _call("POST", "/api/agent/auth/oauth/complete", token, payload)
    if err:
        return err
    data = data or {}
    return {
        "available": True,
        "ok": True,
        "provider": data.get("provider"),
        # Identity only. The token itself stays inside Hermes' credential store
        # and is never returned to the browser.
        "credential": data.get("credential") or {},
    }


def auth_logout(handler, provider: str, query: str = "") -> dict:
    """Remove stored credentials for a provider."""
    token = _token_or_none(handler)
    if not token:
        return _unavailable("not signed in to the Sentry Gateway", 401)
    provider = (provider or "").strip()
    if not provider:
        return _unavailable("provider is required", 400)

    path = f"/api/agent/auth/providers/{quote(provider)}"
    credential = (parse_qs(query or "").get("credential") or [""])[0].strip()
    if credential:
        path = f"{path}?credential={quote(credential)}"

    data, err = _call("DELETE", path, token)
    if err:
        return err
    return {"available": True, "ok": True, **(data or {})}
