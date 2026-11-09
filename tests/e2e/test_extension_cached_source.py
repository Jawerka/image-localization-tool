"""Настоящий HTTP-кэш Chromium и чтение пикселей без пользовательского профиля."""

from __future__ import annotations

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def picture_server():
    image = Image.new("RGB", (23, 31), (12, 64, 180))
    image.putpixel((0, 0), (255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    state = {"image_requests": 0, "offline": False}

    class Handler(BaseHTTPRequestHandler):
        """Считаем запросы, чтобы отличить кэш от повторного скачивания."""

        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.endswith(".png"):
                state["image_requests"] += 1
                data = png
                content_type = "image/png"
                status = 503 if state["offline"] else 200
            else:
                data = b'<img id="pic" src="/image.png">'
                content_type = "text/html"
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            if self.path == "/cors.png":
                self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state, png
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def cached_page(picture_server):
    base, state, png = picture_server
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base + "/page")
        page.locator("#pic").evaluate("img => img.decode()")
        page.add_script_tag(path=str(ROOT / "extension/src/image-source.js"))
        try:
            yield page, context, base, state, png
        finally:
            browser.close()


def test_cached_original_is_read_offline_without_new_request(cached_page):
    page, context, base, state, png = cached_page
    assert state["image_requests"] == 1
    state["offline"] = True
    context.set_offline(True)
    result = page.evaluate("""async () => {
        const node = document.querySelector('#pic');
        const logs = [];
        const bytes = await iltImageSource.read({node, url:node.currentSrc}, (...entry) => logs.push(entry));
        return {bytes, logs};
    }""")
    assert base64.b64decode(result["bytes"]["imageBase64"]) == png
    assert result["logs"][-1][2]["path"] == "page-fetch"
    assert state["image_requests"] == 1


def test_loaded_pixels_keep_full_resolution_when_fetch_fails(cached_page):
    page, _context, _base, _state, png = cached_page
    result = page.evaluate("""async () => {
        window.fetch = async () => { throw new TypeError('offline'); };
        const node = document.querySelector('#pic');
        return iltImageSource.read({node, url:node.currentSrc});
    }""")
    with Image.open(BytesIO(base64.b64decode(result["imageBase64"]))) as recovered:
        with Image.open(BytesIO(png)) as original:
            assert recovered.size == original.size
            assert recovered.convert("RGB").tobytes() == original.convert("RGB").tobytes()


def test_cross_origin_pixels_remain_protected(cached_page):
    page, _context, base, _state, _png = cached_page
    # localhost и 127.0.0.1 — разные origin, хотя ресурс на том же сервере.
    foreign = base.replace("127.0.0.1", "localhost") + "/foreign.png"
    result = page.evaluate("""async url => {
        const node = document.querySelector('#pic');
        node.src = url;
        await node.decode();
        const logs = [];
        const bytes = await iltImageSource.read({node, url:node.currentSrc}, (...entry) => logs.push(entry));
        return {bytes, logs};
    }""", foreign)
    assert result["bytes"] == {}
    assert result["logs"][-1][2]["name"] == "SecurityError"


def test_external_cached_original_with_cors_is_read_offline(cached_page):
    page, context, base, state, png = cached_page
    foreign = base.replace("127.0.0.1", "localhost") + "/cors.png"
    page.locator("#pic").evaluate("(img,url) => {img.src=url; return img.decode();}", foreign)
    count = state["image_requests"]
    state["offline"] = True
    context.set_offline(True)
    result = page.evaluate("""async () => {
        const node = document.querySelector('#pic');
        const logs = [];
        const bytes = await iltImageSource.read({node,url:node.currentSrc}, (...entry) => logs.push(entry));
        return {bytes,logs};
    }""")
    assert base64.b64decode(result["bytes"]["imageBase64"]) == png
    assert result["logs"][-1][2]["path"] == "page-fetch"
    assert state["image_requests"] == count
