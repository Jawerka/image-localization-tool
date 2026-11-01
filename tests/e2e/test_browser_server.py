"""Браузерный transport end-to-end без моделей; реальный pipeline проверяется отдельно."""

import threading

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from src.app.jobs import JobQueue
from src.app.server import AppState, serve
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker

pytestmark = pytest.mark.ui


def test_browser_login_upload_edit_download(tmp_path):
    store = ProjectStore(tmp_path / "data")
    state = AppState(AppSettings(first_run_complete=True, ocr_backend="rapid", translator_backend="argos"),
                     tmp_path / "settings.json", store, JobQueue(FakeWorker(store)), token="browser-test-token")
    httpd, port = serve(state, origins=("http://127.0.0.1", "http://localhost"))
    state.browser_origins = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    image = tmp_path / "page.png"
    Image.new("RGB", (320, 240), "white").save(image)
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
            expect(page.locator("html[data-ilt-booted='1']")).to_have_count(1, timeout=30000)
            expect(page.locator("[data-role='empty'] [data-role='open-files']")).to_be_visible()
            expect(page.locator("[data-role='screen-error']")).to_be_hidden()
            with page.expect_file_chooser() as chooser:
                page.locator("[data-role='empty'] [data-role='open-files']").click()
            chooser.value.set_files(image)
            expect(page.locator("[data-role='page-list']")).to_contain_text("page.png")
            page.reload()
            expect(page.locator("[data-role='page-list']")).to_contain_text("page.png")
            page.locator("[data-role='translate-all']").click()
            expect(page.locator("[data-role='region-list']")).to_contain_text("Привет", timeout=15000)
            page.locator("[data-role='region-list']").get_by_text("Hello", exact=True).click()
            page.locator(".region-card--selected [data-region-tab='text']").click()
            with page.expect_response(lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok):
                page.locator("[data-field='translation']").fill("Браузерный перевод")
            page.locator("[data-role='export']:visible").click()
            expect(page.locator("[data-role='export-browse']")).to_be_hidden()
            with page.expect_download(timeout=20000) as exported:
                page.locator("[data-role='export-go']").click()
            assert exported.value.suggested_filename == "translated-pages.zip"
            assert exported.value.failure() is None
            with page.expect_download(timeout=20000) as packaged:
                page.keyboard.press("Control+s")
            assert packaged.value.suggested_filename == "project.ilt.zip"
            assert packaged.value.failure() is None
            assert errors == []
            browser.close()
    finally:
        state.queue.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
