"""Смоук окна в браузере: сервер как у настольного приложения, без pywebview и без процесса воркера.

``launch()`` не вызывается: ``_build_server`` всегда ставит ``ProcessWorker``.
Здесь сервер собирается в фикстуре на ``FakeWorker``.
"""

from __future__ import annotations

import re
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
    """Вкладки инспектора, раздел сети и панель прогона."""
    expect(page.locator("#tab-text")).to_be_visible()
    expect(page.locator("#tab-page")).to_be_visible()
    expect(page.locator("#tab-style")).to_have_count(0)
    page.locator("#tab-page").click()
    expect(page.locator("#panel-page")).to_be_visible()

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


def _open_and_translate(tab) -> None:
    tab.locator("[data-role='empty'] [data-role='open-files']").click()
    _wait_page_listed(tab)
    tab.locator("[data-role='translate-all']").click()
    _wait_ready(tab)
    tab.wait_for_function(
        """() => {
          const img = document.querySelector("[data-role='img-base']");
          return Boolean(img && img.naturalWidth > 0 && img.complete);
        }"""
    )


@pytest.mark.ui
def test_warp_details_survive_inspector_rebuild(page):
    """Закрытое «Искривление» не открывается снова после rebuild карточки."""
    _open_and_translate(page)
    regions = page.locator("[data-role='region-list']")
    expect(regions).to_contain_text("Привет")
    regions.get_by_text("Hello", exact=True).click()
    warp = page.locator("details.region-card__warp")
    expect(warp).to_be_visible()
    expect(warp).to_have_js_property("open", True)
    warp.locator("summary").click()
    expect(warp).to_have_js_property("open", False)

    translation = page.locator("[data-field='translation']")
    expect(translation).to_be_visible()
    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ):
        translation.fill("Карточка-стабильность")
    expect(translation).to_have_value("Карточка-стабильность")
    expect(page.locator("details.region-card__warp")).to_have_js_property("open", False)


@pytest.mark.ui
def test_mask_draft_then_done_commits(page):
    """Кисть сразу рисует локальную маску; «Готово» снимает deferApply и сохраняет документ."""
    _open_and_translate(page)
    page.locator("[data-role='layer-mask']").click()
    page.locator("[data-role='tool-brush']").click()
    expect(page.locator("[data-role='tool-brush']")).to_have_attribute("aria-checked", "true")

    frame = page.locator("[data-role='frame']")
    expect(frame).to_be_visible()
    box = frame.bounding_box()
    assert box and box["width"] > 0 and box["height"] > 0
    x = box["x"] + box["width"] * 0.35
    y = box["y"] + box["height"] * 0.35
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + max(8.0, box["width"] * 0.2), y + max(8.0, box["height"] * 0.2))
    page.mouse.up()

    apply_edits = page.locator("[data-role='apply-edits']")
    expect(apply_edits).to_be_visible()
    expect(apply_edits).to_be_enabled()
    local = page.locator("[data-role='mask-local']")
    expect(local).not_to_be_hidden()
    expect(frame).to_have_class(re.compile(r"frame--mask-draft"))

    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ):
        apply_edits.click()
    expect(apply_edits).to_be_hidden()
