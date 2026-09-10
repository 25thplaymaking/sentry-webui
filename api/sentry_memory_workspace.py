"""Narrow personal-memory proxy, composed AFTER the WebUI's existing auth guard.

No client-controlled Gateway URL, profile target, token, or filesystem path is
accepted. Existing Hermes /api/memory and agent approval routes are untouched.
"""
from __future__ import annotations

import json
import re
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from uuid import UUID

PREFIX = "/api/sentry/profile-memory"
MAX_BODY_BYTES = 2 * 1024 * 1024
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_ASSETS = {
    "/static/sentry_workspace.js": ("sentry_workspace.js", "text/javascript"),
    "/static/sentry_workspace.css": ("sentry_workspace.css", "text/css"),
    "/sentry_workspace.js": ("sentry_workspace.js", "text/javascript"),
    "/sentry_workspace.css": ("sentry_workspace.css", "text/css"),
}
_SECTION = re.compile(r"[A-Za-z0-9_.\-]{1,64}")


def _respond(handler, data, status=200):
    body = b"" if status == 204 else json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD" and body:
        handler.wfile.write(body)
    return True


def _error(handler, status, message):
    return _respond(handler, {"error": message}, status)


def _origin_allowed(handler) -> bool:
    if handler.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return False
    origin = handler.headers.get("Origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
                return False
            if parsed.netloc.lower() != handler.headers.get("Host", "").lower():
                return False
        except ValueError:
            return False
    return True


def _payload(handler) -> dict:
    if handler.headers.get("Transfer-Encoding"):
        raise ValueError("Chunked memory requests are not supported.")
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("Send application/json.")
    try:
        size = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Invalid Content-Length.") from exc
    if size < 2 or size > MAX_BODY_BYTES:
        raise ValueError("Memory request is empty or too large.")
    raw = handler.rfile.read(size)
    if len(raw) != size:
        raise ValueError("Incomplete memory request.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON.") from exc
    required = {"content", "expected_updated_at", "expected_profile_id"}
    if not isinstance(body, dict) or set(body) != required:
        raise ValueError("Content, expected_updated_at and expected_profile_id are required.")
    if not isinstance(body["content"], str) or len(body["content"]) > 200_000:
        raise ValueError("Memory content must be text of at most 200,000 characters.")
    if body["expected_updated_at"] is not None and not isinstance(body["expected_updated_at"], str):
        raise ValueError("Invalid memory version.")
    try:
        UUID(body["expected_profile_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid expected profile.") from exc
    return body


def wrap_memory_route(original):
    """Wrap only exact namespace routes; everything else keeps its old handler."""
    @wraps(original)
    def route(handler, parsed):
        # Constant assets only: no path traversal and no changes to the huge
        # upstream static-route table. The existing Handler auth check ran first.
        if parsed.path in _ASSETS and handler.command == "GET":
            filename, mime = _ASSETS[parsed.path]
            try:
                body = (_STATIC_DIR / filename).read_bytes()
            except FileNotFoundError:
                return _error(handler, 404, "Workspace asset is not installed.")
            handler.send_response(200)
            handler.send_header("Content-Type", mime + "; charset=utf-8")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return True
        if parsed.path != PREFIX and not parsed.path.startswith(PREFIX + "/"):
            return original(handler, parsed)
        from api.gateway_chat import _gateway_dialect, sentry_access_token_from_handler
        from api.sentry_gateway_client import SentryGatewayError, get_json, put_json, delete_json
        if _gateway_dialect() != "sentry":
            return _error(handler, 404, "Personal Sentry memory is not available in this dialect.")
        if not _origin_allowed(handler):
            return _error(handler, 403, "Cross-origin memory requests are not allowed.")
        token = sentry_access_token_from_handler(handler)
        if not token:
            return _error(handler, 401, "Sign in to Sentry to manage personal memory.")
        method = handler.command
        if method not in ("GET", "PUT", "DELETE"):
            return _error(handler, 405, "Method not allowed.")
        if method != "GET" and handler.headers.get("X-Sentry-Workspace") != "1":
            return _error(handler, 403, "Missing memory workspace request header.")
        try:
            if method == "GET" and parsed.path == PREFIX:
                data = get_json("/api/memory/workspace", token)
                if not isinstance(data, dict) or not isinstance(data.get("sections"), list) or not data.get("profile_id"):
                    return _error(handler, 502, "The Gateway memory contract is unavailable. Install the paired Gateway update.")
                return _respond(handler, data)
            section = unquote(parsed.path[len(PREFIX) + 1:])
            if not _SECTION.fullmatch(section):
                return _error(handler, 400, "Invalid memory section.")
            path = "/api/memory/" + quote(section, safe="")
            if method == "PUT":
                return _respond(handler, put_json(path, token, _payload(handler)))
            if method == "DELETE":
                query = parse_qs(parsed.query, keep_blank_values=True)
                required = {"expected_updated_at", "expected_profile_id"}
                if set(query) != required or any(len(v) != 1 or not v[0] for v in query.values()):
                    raise ValueError("The original memory version and profile are required to delete.")
                UUID(query["expected_profile_id"][0])
                if len(query["expected_updated_at"][0]) > 64:
                    raise ValueError("Invalid memory version.")
                delete_json(path + "?" + urlencode({k: v[0] for k, v in query.items()}), token)
                return _respond(handler, None, 204)
            return _error(handler, 405, "Method not allowed for this route.")
        except SentryGatewayError as exc:
            code = exc.status if isinstance(exc.status, int) and 400 <= exc.status <= 599 else 503
            # Do not forward local transport addresses, tokens, or stack traces.
            message = str(exc) if code in (400, 401, 403, 409, 422) else "Gateway memory is unavailable. Your unsaved text has not been discarded."
            return _error(handler, code, message)
        except (ValueError, TypeError) as exc:
            return _error(handler, 400, str(exc))
    return route
