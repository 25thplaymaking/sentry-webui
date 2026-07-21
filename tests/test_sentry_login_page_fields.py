"""The login page must show the door that actually works.

Once password sign-in is refused (sentry dialect), rendering a password box is
a trap: the user types the shared password and is rejected every time. The page
should offer the enrollment field alone, and it must carry the autofocus that
the password box used to own.
"""

import api.routes as routes


def _sentry(monkeypatch, *, allow_password=False):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "sentry")
    if allow_password:
        monkeypatch.setenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", "1")
    else:
        monkeypatch.delenv("HERMES_WEBUI_SENTRY_ALLOW_PASSWORD", raising=False)


def test_password_input_is_dropped_when_password_login_is_refused(monkeypatch):
    _sentry(monkeypatch)
    assert routes._login_password_html() == ""


def test_password_input_is_rendered_for_shared_password_deployments(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GATEWAY_DIALECT", "hermes")
    html = routes._login_password_html()
    assert 'type="password"' in html
    assert 'id="pw"' in html
    assert "autofocus" in html


def test_password_input_returns_when_the_escape_hatch_is_set(monkeypatch):
    _sentry(monkeypatch, allow_password=True)
    assert 'type="password"' in routes._login_password_html()


def test_enrollment_field_takes_autofocus_when_it_is_the_only_door(monkeypatch):
    _sentry(monkeypatch)
    enroll = routes._sentry_enroll_html()
    assert 'id="enroll-code"' in enroll
    assert "autofocus" in enroll, "the only input on the page must be focused"


def test_enrollment_field_does_not_steal_autofocus_from_password(monkeypatch):
    """With the escape hatch on, both fields render — password keeps autofocus."""
    _sentry(monkeypatch, allow_password=True)
    assert "autofocus" not in routes._sentry_enroll_html()


def test_login_template_uses_the_password_placeholder():
    """Guard the wiring: the template must render through the helper."""
    assert "{{PASSWORD_INPUT_HTML}}" in routes._LOGIN_PAGE_HTML
