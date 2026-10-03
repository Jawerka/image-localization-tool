"""Смоук окна в браузере: сервер как у настольного приложения, без pywebview и без процесса воркера.

``launch()`` не вызывается: ``_build_server`` всегда ставит ``ProcessWorker``.
Здесь сервер собирается в фикстуре на ``FakeWorker``.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from src.app.dialogs import DialogBridge
from src.app.jobs import JobQueue
from src.app.server import AppState, serve
from src.app.settings import AppSettings
from src.app.store import ProjectStore
from src.app.worker import FakeWorker

pytestmark = pytest.mark.ui


class _ScriptedDialogs(DialogBridge):
    """Одна картинка и одна папка экспорта, без системных окон."""

    def __init__(self, image: Path, export_dir: Path):
        self._image = image
        self._export_dir = export_dir

    def open_files(self) -> list[Path]:
        return [self._image]

    def pick_directory(self) -> Path | None:
        return self._export_dir


def _silence_keyring(monkeypatch) -> None:
    """Смоук не должен трогать хранилище ключей Windows."""
    module = types.ModuleType("keyring")
    module.get_password = lambda _service, _username: None
    module.set_password = lambda _service, _username, _value: None
    module.delete_password = lambda _service, _username: None
    monkeypatch.setitem(sys.modules, "keyring", module)


def _wait_until_listening(port: int) -> None:
    deadline = time.time() + 5
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.02)
    raise RuntimeError(f"Сервер не слушает порт {port}: {last_error}")


@pytest.fixture
def browser():
    """Свой Chromium на тест. Общий браузер на сессию замирает на втором окне."""
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        try:
            yield chromium
        finally:
            chromium.close()


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    """Временный сервер: мастер уже пройден, диалоги заранее знают пути."""
    _silence_keyring(monkeypatch)
    image = tmp_path / "page.png"
    Image.new("RGB", (32, 32), "white").save(image)
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    store = ProjectStore(tmp_path / "store")
    settings = AppSettings(first_run_complete=True)
    state = AppState(
        settings=settings,
        settings_path=tmp_path / "settings.json",
        store=store,
        queue=JobQueue(FakeWorker(store, synchronous=True)),
        dialogs=_ScriptedDialogs(image, export_dir),
    )
    httpd, port = serve(state)
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="ilt-ui-smoke",
        daemon=True,
    )
    thread.start()
    _wait_until_listening(port)
    try:
        yield types.SimpleNamespace(port=port, token=state.token, export_dir=export_dir, image=image)
    finally:
        state.queue.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def page(browser, desktop):
    expect.set_options(timeout=15_000)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    tab = context.new_page()
    tab.set_default_timeout(15_000)
    url = f"http://127.0.0.1:{desktop.port}/?k={desktop.token}"
    with tab.expect_response(lambda response: "/api/bootstrap" in response.url and response.ok):
        tab.goto(url)
    expect(tab.locator("[data-role='screen-wizard']")).to_be_hidden()
    expect(tab.locator("[data-role='screen-error']")).to_be_hidden()
    expect(tab.locator("[data-role='shell']")).to_be_visible()
    expect(tab.locator("[data-role='empty']")).to_be_visible()
    try:
        yield tab
    finally:
        context.close()


def _wait_page_listed(tab) -> None:
    expect(tab.locator("[data-role='page-list']")).to_contain_text("page.png")


def _wait_ready(tab) -> None:
    expect(tab.locator("[data-role='page-list'] .page__status")).to_contain_text("готово")


def _export_proof(tab, export_dir: Path) -> str:
    files = sorted(path.name for path in export_dir.iterdir() if path.is_file())
    if files:
        return ", ".join(files)
    text = tab.locator("[data-role='banners']").inner_text()
    if "Сохранено" in text:
        return text.strip()
    return ""


def _wait_export(tab, export_dir: Path) -> str:
    """Файл в папке или баннер «Сохранено»."""
    deadline = time.time() + 15
    last_banner = ""
    while time.time() < deadline:
        proof = _export_proof(tab, export_dir)
        if proof:
            return proof
        last_banner = tab.locator("[data-role='banners']").inner_text().strip()
        tab.wait_for_timeout(100)
    return last_banner


@pytest.mark.ui
def test_open_translate_edit_and_export(page, desktop):
    """Файлы, перевод, правка, новый регион и экспорт."""
    page.locator("[data-role='empty'] [data-role='open-files']").click()
    _wait_page_listed(page)

    page.locator("[data-role='translate-all']").click()
    _wait_ready(page)

    regions = page.locator("[data-role='region-list']")
    expect(regions).to_contain_text("Привет")
    regions.get_by_text("Hello", exact=True).click()
    translation = page.locator("[data-field='translation']")
    expect(translation).to_be_visible()
    with page.expect_response(lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok):
        translation.fill("Смоук-перевод")
    expect(translation).to_have_value("Смоук-перевод")

    page.locator("[data-role='add-region']").click()
    expect(page.locator("[data-role='region-list'] [data-region-id]")).to_have_count(2)

    page.locator("[data-role='export']:visible").click()
    expect(page.locator("[data-dialog='export']")).to_be_visible()
    page.locator("[data-role='export-go']").click()
    proof = _wait_export(page, desktop.export_dir)
    files = [path.name for path in desktop.export_dir.iterdir() if path.is_file()]
    assert files or "Сохранено" in proof, (
        f"в папке экспорта нет файла и баннер не показал итог: {proof!r}"
    )


@pytest.mark.ui
def test_keyboard_open_translate_and_hotkeys(page):
    """Только клавиатура: открыть, перевести всё, список клавиш и закрыть его."""
    page.locator("a.skip").focus()
    page.keyboard.press("Control+o")
    _wait_page_listed(page)

    page.keyboard.press("Control+Shift+Enter")
    _wait_ready(page)

    page.keyboard.press("F1")
    expect(page.locator("[data-dialog='hotkeys']")).to_be_visible()
    expect(page.locator("#hotkeys-title")).to_have_text("Горячие клавиши")

    page.keyboard.press("Escape")
    expect(page.locator("[data-role='modals']")).to_be_hidden()
    expect(page.locator("[data-dialog='hotkeys']")).to_be_hidden()


@pytest.mark.ui
def test_style_network_and_batch_panels(page):
    """Вкладка стиля, раздел сети и панель прогона."""
    page.locator("#tab-style").click()
    expect(page.locator("#panel-style")).to_be_visible()
    expect(page.locator("#panel-style")).to_contain_text("Регион не выбран")

    page.locator("button.btn-icon[data-role='settings']").click()
    page.locator("#nav-network").click()
    expect(page.locator("#sec-network")).to_be_visible()
    expect(page.locator("#sec-network")).to_contain_text("Доступ по сети")
    expect(page.locator("#sec-network")).to_contain_text("HTTP")
    page.locator("[data-role='settings-cancel']").click()
    expect(page.locator("[data-role='screen-settings']")).to_be_hidden()

    page.locator("[data-role='empty'] [data-role='open-files']").click()
    _wait_page_listed(page)
    fold = page.locator("[data-role='batch-fold']")
    expect(fold).to_be_visible()
    fold.locator("summary").click()
    expect(fold).to_contain_text("Страницы проекта")
