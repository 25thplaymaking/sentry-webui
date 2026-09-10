"""Tests verifying sidebar session visibility and linked-session-hub constraints."""
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def test_panels_resync_recovers_empty_session_list():
    panels_js = (STATIC_DIR / "panels.js").read_text(encoding="utf-8")
    assert "_resyncChatSidebarAfterPanelSwitch" in panels_js
    assert "renderSessionListFromCache()" in panels_js
    assert "renderSessionList({deferWhileInteracting: false})" in panels_js
    assert "renderSessionList({deferWhileInteracting: true})" in panels_js
    assert "listEmpty" in panels_js or "session-item" in panels_js


def test_style_css_bounds_linked_session_hub():
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert ".linked-session-hub{margin:0 10px 8px;border:1px solid var(--border);border-radius:10px;" in style_css
    assert "max-height:min(260px,34vh)" in style_css
    assert "display:flex;flex-direction:column" in style_css
    assert ".linked-session-groups{" in style_css
    assert "overflow-y:auto" in style_css
    assert ".session-list{" in style_css
    assert "min-height:100px" in style_css


def test_linked_session_hub_collapse_support():
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "toggleLinkedSessionHubCollapse()" in index_html
    assert "linked-session-hub-title" in index_html

    integrations_js = (STATIC_DIR / "sentry_integrations.js").read_text(encoding="utf-8")
    assert "function toggleLinkedSessionHubCollapse(" in integrations_js
    assert "function syncLinkedSessionHubCollapse(" in integrations_js
    assert "toggleLinkedSessionHubCollapse" in integrations_js
    assert "sentry-linked-sessions-collapsed" in integrations_js

    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert ".linked-session-hub.is-collapsed" in style_css


def test_sessions_close_provider_on_open_and_new():
    sessions_js = (STATIC_DIR / "sessions.js").read_text(encoding="utf-8")
    assert "closeLinkedProviderSession" in sessions_js

    boot_js = (STATIC_DIR / "boot.js").read_text(encoding="utf-8")
    assert "closeLinkedProviderSession" in boot_js
