"""Browser-side plumbing for identity-provider account recovery.

The browser never reaches the Sentry Gateway -- it reaches this fork, which
proxies. That leaves two things to carry across a redirect to the provider and
back, and this module owns both:

1. The Gateway's opaque ``flow_token``, which holds the PKCE verifier. It is
   signed by the Gateway; this fork stores it and hands it back without reading
   it.

2. The recovery code the Gateway mints once the provider has been verified.

The second one deliberately never touches the browser. The obvious shortcut --
redirecting to the login page with the code in the URL fragment -- would write a
live credential into browser history and into anything reading the address bar.
Instead the code is held here against a random ticket, the ticket goes to the
browser in an HttpOnly cookie, and the login page posts only the new password.
The code is then spent server-side through the same unchanged
``password_recover`` path Server Control's flow uses.
"""

from __future__ import annotations

import http.cookies
import secrets
import threading
import time

#: Matches the Gateway's own recovery-code lifetime. There is no value in
#: holding a ticket longer than the code behind it stays valid.
TICKET_TTL_SECONDS = 600

FLOW_COOKIE = "sentry_oidc_flow"
TICKET_COOKIE = "sentry_oidc_ticket"

_lock = threading.Lock()
#: ticket id -> (username, recovery code, expiry epoch seconds)
_tickets: dict[str, tuple[str, str, float]] = {}


def _prune_locked(now: float) -> None:
    for key in [key for key, entry in _tickets.items() if entry[2] <= now]:
        _tickets.pop(key, None)


def issue_ticket(username: str, code: str) -> str:
    """Park a verified recovery code and return the ticket that redeems it."""
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        _prune_locked(now)
        _tickets[ticket] = (username, code, now + TICKET_TTL_SECONDS)
    return ticket


def consume_ticket(ticket: str | None) -> tuple[str, str] | None:
    """Spend a ticket exactly once. None if unknown, already spent, or expired."""
    if not ticket:
        return None
    now = time.time()
    with _lock:
        _prune_locked(now)
        entry = _tickets.pop(ticket, None)
    if entry is None or entry[2] <= now:
        return None
    return entry[0], entry[1]


def _cookie_header(name: str, value: str, *, secure: bool, max_age: int) -> str:
    cookie = http.cookies.SimpleCookie()
    cookie[name] = value
    cookie[name]["httponly"] = True
    cookie[name]["path"] = "/"
    # Lax, not Strict: the provider redirect is a cross-site top-level
    # navigation, and a Strict cookie would simply not be sent with it.
    cookie[name]["samesite"] = "Lax"
    cookie[name]["max-age"] = str(max_age)
    if secure:
        cookie[name]["secure"] = True
    return cookie[name].OutputString()


def set_cookie_header(name: str, value: str, *, secure: bool) -> str:
    return _cookie_header(name, value, secure=secure, max_age=TICKET_TTL_SECONDS)


def clear_cookie_header(name: str) -> str:
    return _cookie_header(name, "", secure=False, max_age=0)


def read_cookie(handler, name: str) -> str | None:
    raw = handler.headers.get("Cookie", "")
    if not raw:
        return None
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(raw)
    except http.cookies.CookieError:
        return None
    morsel = cookie.get(name)
    return morsel.value if morsel else None
