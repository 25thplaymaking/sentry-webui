"""The login page must show the door that actually works.

Once SHARED-password sign-in is refused (sentry dialect), rendering the shared
password box is a trap: the user types the deployment password and is rejected
every time. It stays withheld.

What replaced it is a per-user credential -- username + password, checked by the
Gateway -- rendered by `_sentry_credential_html()`. That is a different control
with different ids, and it is what now carries the autofocus. The enrollment
code stays on the page beside it for pairing a device.
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


def test_shared_password_box_yields_autofocus_to_the_per_user_credential(monkeypatch):
    """With the escape hatch on, both render. Two autofocus attributes on one
    form is a bug even though the browser quietly honours the first."""
    _sentry(monkeypatch, allow_password=True)
    assert "autofocus" not in routes._login_password_html()
    assert "autofocus" in routes._sentry_credential_html()


def test_enrollment_field_is_still_offered(monkeypatch):
    """It is no longer the only door -- username+password is the normal one --
    but it is still how a fresh device pairs and how someone with no password
    yet gets in, so it must keep rendering."""
    _sentry(monkeypatch)
    assert 'id="enroll-code"' in routes._sentry_enroll_html()


def test_autofocus_lands_on_the_first_usable_field(monkeypatch):
    """That field used to be the enrollment code, because it was the only input
    on the page. It is now the username, so the focus moved with it."""
    _sentry(monkeypatch)
    assert "autofocus" in routes._sentry_credential_html()
    assert "autofocus" not in routes._sentry_enroll_html()


def test_enrollment_field_does_not_steal_autofocus_with_the_escape_hatch_on(monkeypatch):
    """With the escape hatch on, the shared-password box renders too. The
    enrollment code must not fight either of the other two for focus."""
    _sentry(monkeypatch, allow_password=True)
    assert "autofocus" not in routes._sentry_enroll_html()


def test_login_template_uses_the_password_placeholder():
    """Guard the wiring: the template must render through the helper."""
    assert "{{PASSWORD_INPUT_HTML}}" in routes._LOGIN_PAGE_HTML
