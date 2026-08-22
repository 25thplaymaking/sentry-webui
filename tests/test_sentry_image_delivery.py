"""Sentry image paste is visible and reaches the authenticated Gateway turn."""

import io
import json
import threading
from pathlib import Path

from api import gateway_chat


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
PANELS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
BOOT = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
UI = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def test_sentry_product_keeps_the_real_image_attachment_controls_visible():
    start = CSS.index('[data-sentry-product="true"] .composer-ws-wrap')
    end = CSS.index("{display:none!important;}", start)
    hidden_block = CSS[start:end]

    assert "#btnAttach" not in hidden_block
    assert "#attachTray" not in hidden_block
    assert "#dropHint" not in hidden_block
    assert "const unavailable=new Set(['hide_composer_workspace','hide_composer_reasoning'])" in PANELS


def test_paste_confirmation_only_names_images_the_composer_accepted():
    assert "const accepted=[];" in UI
    assert "return accepted;" in UI
    assert "if(accepted.length)setStatus(t('image_pasted')" in BOOT


def test_sentry_turn_posts_validated_image_data_to_gateway(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["authorization"] = request.headers.get("Authorization")
        return _Response(b"data: [DONE]\n\n")

    monkeypatch.setattr(gateway_chat.urllib.request, "urlopen", fake_urlopen)

    gateway_chat._run_sentry_turn_streaming(
        "session-1",
        "Describe this image.",
        "stream-1",
        "https://gateway.example",
        "user-token",
        put_gateway_event=lambda *_args: None,
        cancel_event=threading.Event(),
        images=[{"data_url": PNG_DATA_URL}],
    )

    assert captured["authorization"] == "Bearer user-token"
    assert captured["body"]["images"] == [{"data_url": PNG_DATA_URL}]


def test_sentry_image_builder_reads_only_a_valid_image_inside_the_workspace(tmp_path):
    image = tmp_path / "pasted.png"
    image.write_bytes(__import__("base64").b64decode(PNG_DATA_URL.split(",", 1)[1]))
    outside = tmp_path.parent / "outside-pasted.png"
    outside.write_bytes(image.read_bytes())
    try:
        inputs = gateway_chat._sentry_image_inputs(
            [
                {"path": str(image), "mime": "image/png"},
                {"path": str(outside), "mime": "image/png"},
            ],
            str(tmp_path),
        )
    finally:
        outside.unlink(missing_ok=True)

    assert inputs == [{"data_url": PNG_DATA_URL}]
