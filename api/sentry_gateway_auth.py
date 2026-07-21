"""Client for the Sentry Gateway device-enrolment auth API.

Used only in the ``sentry`` gateway dialect (see ``gateway_chat._gateway_dialect``).
A WebUI user redeems a Gateway enrollment code for a per-user token pair, and the
WebUI rotates it as the refresh token rotates. The Gateway base URL is the same
one chat uses (``HERMES_WEBUI_GATEWAY_BASE_URL`` -> ``http://sentry-gateway:8090``).

Endpoints (from the Gateway ``app/routes/auth.py``):
    POST /api/auth/enroll/complete  {code, device_name} -> token pair (unauth)
    POST /api/auth/refresh          {refresh_token}      -> rotated token pair
Token pair shape: {access_token, refresh_token, device_id, profile_id}.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request


def jwt_exp(token) -> float | None:
    """Best-effort read of a JWT's ``exp`` claim (epoch seconds), WITHOUT
    verifying the signature. Used only to decide when to proactively refresh;
    the Gateway remains the authority on validity. Returns None if unreadable.
    """
    try:
        parts = str(token).split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


class SentryAuthError(Exception):
    """A Gateway auth call failed. ``status`` is the HTTP code when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _read_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])
    except Exception:
        pass
    return f"gateway error {exc.code}"


def _post(base_url: str, path: str, payload: dict, *, timeout: float = 15.0) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SentryAuthError(_read_detail(exc), status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise SentryAuthError(f"gateway unreachable: {exc.reason}") from exc
    if not isinstance(parsed, dict):
        raise SentryAuthError("gateway returned an unexpected response")
    return parsed


def enroll_complete(base_url: str, code: str, device_name: str, *, timeout: float = 15.0) -> dict:
    """Redeem a single-use enrollment code for a token pair.

    Returns ``{access_token, refresh_token, device_id, profile_id}``. Raises
    ``SentryAuthError`` (status 400) if the code is invalid/expired/used.
    """
    return _post(
        base_url, "/api/auth/enroll/complete",
        {"code": code, "device_name": device_name}, timeout=timeout,
    )


def refresh(base_url: str, refresh_token: str, *, timeout: float = 15.0) -> dict:
    """Rotate a refresh token, returning a fresh token pair.

    The presented refresh token is retired by the Gateway on use, so the caller
    MUST persist the returned ``refresh_token`` or the next refresh will fail.
    """
    return _post(
        base_url, "/api/auth/refresh",
        {"refresh_token": refresh_token}, timeout=timeout,
    )
