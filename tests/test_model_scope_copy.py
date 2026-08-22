from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_composer_model_dropdown_has_scope_advisory():
    ui = read("static/ui.js")
    style = read("static/style.css")

    assert "model-scope-note" in ui
    assert "model-scope-note-lead" in ui
    assert "model-scope-note-detail" in ui
    assert "_scopeNote.setAttribute('role','note')" in ui
    assert "model_scope_advisory" in ui
    assert "Applies to this conversation from your next message." in ui
    assert "_pickerHeader.appendChild(_scopeNote);" in ui
    assert "_pickerHeader.appendChild(_searchRow);" in ui
    assert "dd.appendChild(_pickerHeader);" in ui
    assert "dd.appendChild(_scopeNote);" not in ui
    assert "dd.appendChild(_searchRow);" not in ui
    assert ".model-scope-note" in style
    assert ".model-picker-header{position:sticky" in style


def test_model_selection_toast_describes_conversation_scope():
    boot = read("static/boot.js")
    i18n = read("static/i18n.js")

    assert "model_scope_toast" in boot
    assert "Applies to this conversation from your next message." in i18n
    assert "model_scope_advisory: 'Applies to this conversation from your next message.'" in i18n
    assert "model_scope_toast: 'Applies to this conversation from your next message.'" in i18n
    assert "Model change takes effect in your next conversation" not in boot


def test_settings_default_model_copy_describes_new_conversations():
    html = read("static/index.html")
    i18n = read("static/i18n.js")

    assert 'data-i18n="settings_desc_model"' in html
    assert "Used for new conversations. Existing conversations keep their selected model." in html
    assert "settings_desc_model" in i18n
