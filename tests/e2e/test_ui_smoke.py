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
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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
    expect.set_options(timeout=30_000)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    tab = context.new_page()
    tab.set_default_timeout(30_000)
    page_errors: list[str] = []
    tab.on("pageerror", lambda error: page_errors.append(str(error)))
    url = f"http://127.0.0.1:{desktop.port}/?k={desktop.token}"
    last_timeout = None
    for _attempt in range(2):
        try:
            with tab.expect_response(lambda response: "/api/bootstrap" in response.url and response.ok):
                tab.goto(url)
            last_timeout = None
            break
        except PlaywrightTimeoutError as exc:
            last_timeout = exc
            tab.goto("about:blank")
    if last_timeout is not None:
        raise AssertionError(f"bootstrap timeout at {tab.url}; page errors: {page_errors}") from last_timeout
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
    card = regions.locator(".region-card--selected")
    card.locator("[data-region-tab='font']").click()
    font_search = page.locator("[data-font-search]")
    expect(font_search).to_be_visible()
    fonts = page.locator("select[data-field='font_id'] option")
    font_count = fonts.count()
    if font_count > 2:
        font_search.fill(fonts.nth(1).inner_text()[:3])
        expect(fonts.nth(font_count - 1)).to_be_hidden()
        font_search.fill("")
    card.locator("[data-region-tab='text']").click()
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
def test_retranslate_waits_for_latest_text_save_and_sends_version(page):
    """Повторный перевод стартует после сохранения ввода и несёт его версию."""
    import re

    _open_and_translate(page)
    regions = page.locator("[data-role='region-list']")
    regions.get_by_text("Hello", exact=True).click()
    requests = []

    async def intercept_action(route):
        await route.fulfill(status=200, content_type="application/json", body='{"job_id":"stub-job"}')

    page.route(re.compile(r"/api/pages/[^/]+/action$"), intercept_action)
    page.on("request", lambda request: requests.append(request)
            if request.url.endswith("/action") or (request.method == "PUT" and "/document" in request.url) else None)
    page.locator("[data-field='translation']").fill("Самый свежий ввод")
    with page.expect_request(lambda request: request.url.endswith("/action") and request.method == "POST") as action_info:
        page.locator("[data-region-action='retranslate']").click()

    action_request = action_info.value
    action_body = action_request.post_data_json
    assert isinstance(action_body.get("base_version"), int)
    put_indices = [index for index, request in enumerate(requests)
                   if request.method == "PUT" and "/document" in request.url]
    assert put_indices and max(put_indices) < requests.index(action_request)


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
    page.locator("#nav-models").click()
    expect(page.locator("#sec-models")).to_be_visible()
    expect(page.locator("#sec-models")).to_contain_text("Подготовить компоненты")
    page.locator("[data-role='settings-cancel']").click()
    expect(page.locator("[data-role='screen-settings']")).to_be_hidden()

    page.locator("[data-role='empty'] [data-role='open-files']").click()
    _wait_page_listed(page)
    page.locator("#sidebar-tab-queue").click()
    queue = page.locator("#sidebar-panel-queue")
    expect(queue).to_be_visible()
    expect(queue).to_contain_text("Страницы проекта")
    page.locator("#sidebar-tab-pages").click()
    expect(page.locator("#sidebar-panel-pages")).to_be_visible()


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
    """Выбранная вкладка «Трансформация» переживает rebuild инспектора."""
    _open_and_translate(page)
    regions = page.locator("[data-role='region-list']")
    expect(regions).to_contain_text("Привет")
    regions.get_by_text("Hello", exact=True).click()
    card = regions.locator(".region-card--selected")
    transform = card.locator("[data-region-tab='transform']")
    transform.click()
    expect(transform).to_have_attribute("aria-selected", "true")
    expect(card.locator("[data-card-warp='mesh']")).to_be_visible()

    card.locator("[data-region-tab='text']").click()
    translation = page.locator("[data-field='translation']")
    expect(translation).to_be_visible()
    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ):
        translation.fill("Перевод-перестройка")
    expect(translation).to_have_value("Перевод-перестройка")

    card = regions.locator(".region-card--selected")
    expect(card.locator("[data-region-tab='transform']")).to_have_attribute(
        "aria-selected", "false"
    )
    card.locator("[data-region-tab='transform']").click()
    expect(card.locator("[data-card-warp='mesh']")).to_be_visible()


@pytest.mark.ui
def test_inspector_sections_fit_and_remain_open(page):
    """Три вкладки помещаются в 344 px, переключаются и не теряют выбор."""
    _open_and_translate(page)
    regions = page.locator("[data-role='region-list']")
    regions.get_by_text("Hello", exact=True).click()
    card = regions.locator(".region-card--selected")
    tabs = card.locator("[data-region-tab]")
    expect(tabs).to_have_count(3)
    expect(card.locator("[data-region-panel='text']")).to_be_visible()
    expect(card.locator("[data-region-panel='font']")).to_be_hidden()

    card.locator("[data-region-tab='transform']").click()
    expect(card.locator("[data-region-panel='transform']")).to_be_visible()
    expect(card.locator("[data-region-action='geometry']")).to_be_visible()

    page.set_viewport_size({"width": 1280, "height": 800})
    panel_width = page.locator("[data-role='inspector']").evaluate("node => Math.round(node.getBoundingClientRect().width)")
    assert panel_width == 344, f"ширина панели должна быть 344 px, получено {panel_width}"
    for theme in ("light", "dark"):
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        overflow = page.locator("[data-role='inspector']").evaluate(
            "node => node.scrollWidth > node.clientWidth"
        )
        assert not overflow, f"горизонтальный скролл инспектора в теме {theme}"

    card.locator("[data-region-tab='text']").click()
    translation = card.locator("[data-field='translation']")
    translation.fill("Ещё правка")
    expect(translation).to_be_focused()
    expect(card.locator("[data-region-tab='text']")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.locator("[data-region-panel='text']")).to_be_visible()


@pytest.mark.ui
def test_mesh_preset_draws_grid_and_requests_preview(page, desktop):
    """Выбор сетки немедленно рисует узлы и запрашивает точный preview."""
    Image.new("RGB", (320, 180), "white").save(desktop.image)
    _open_and_translate(page)
    page_id = page.locator("[data-role='page-list'] [data-page-id]").get_attribute("data-page-id")
    assert page_id
    with page.expect_response(lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok):
        page.evaluate("""async id => {
          const state = await import('/js/state.js');
          state.editDocument(document => { document.regions[0].bbox = [50, 40, 200, 80]; });
        }""", page_id)
    regions = page.locator("[data-role='region-list']")
    regions.get_by_text("Hello", exact=True).click()
    card = regions.locator(".region-card--selected")
    card.locator("[data-region-tab='transform']").click()
    with page.expect_response(
        lambda response: "/preview-region" in response.url and response.request.method == "POST" and response.ok
    ):
        card.locator("[data-card-warp='mesh']").click()
        page.wait_for_timeout(500)
    canvas = page.locator("[data-role='mesh-preview']")
    page.wait_for_function(
        "document.querySelector('[data-role=mesh-preview]')?.dataset.ready === 'true'",
        timeout=10_000,
    )
    grid = page.locator(".box--selected .box__grid")
    expect(grid).to_be_visible()
    expect(grid.locator("polyline")).to_have_count(8)
    keyboard_node = page.locator(".box--selected .box__point").first
    expect(page.locator(".box--selected .box__point")).to_have_count(16)
    keyboard_node.focus()
    expect(keyboard_node).to_be_focused()
    keyboard_node.press("Tab")
    expect(page.locator(".box--selected .box__point[data-index='1']")).to_be_focused()
    for _ in range(5):
        page.locator("[data-role='zoom-in']").click()
    handle = page.locator(".box--selected .box__point[data-index='15']")
    expect(handle).to_be_visible()
    before = handle.get_attribute("style")
    rect = handle.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 6, rect["y"] + rect["height"] / 2 + 4, steps=4)
    expect(canvas).to_be_visible()
    expect(page.locator("[data-role='style-preview']")).to_be_hidden()
    pixels = canvas.evaluate("""node => {
      const gl = node.getContext('webgl');
      const data = new Uint8Array(node.width * node.height * 4);
      gl.readPixels(0, 0, node.width, node.height, gl.RGBA, gl.UNSIGNED_BYTE, data);
      let visible = 0;
      let transparent = 0;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] > 0) visible += 1;
        if (data[i] === 0) transparent += 1;
      }
      return { visible, transparent };
    }""")
    assert pixels["visible"] > 0 and pixels["transparent"] > 0, f"RGBA-текстура должна содержать и чернила, и прозрачный фон: {pixels}"
    writes = []
    page.on("request", lambda request: writes.append(request.url) if request.method == "PUT" and "/document" in request.url else None)
    assert not writes, "черновой drag не должен сохраняться до отпускания"
    page.mouse.up()
    assert not writes, "отложенная правка не должна сохраняться до команды «Готово»"
    expect(canvas).to_be_visible()
    after = page.locator(".box--selected .box__point[data-index='15']").get_attribute("style")
    assert after != before, "узел сетки должен сохранять новое положение после отпускания"
    page.locator("[data-role='undo']").click()
    assert page.locator(".box--selected .box__point[data-index='15']").get_attribute("style") == before
    page.locator("[data-role='redo']").click()
    assert page.locator(".box--selected .box__point[data-index='15']").get_attribute("style") == after
    group_a = page.locator(".box--selected .box__point[data-index='5']")
    group_b = page.locator(".box--selected .box__point[data-index='6']")
    group_a_before = group_a.get_attribute("style")
    group_b_before = group_b.get_attribute("style")
    group_a.click(modifiers=["Control"])
    group_b = page.locator(".box--selected .box__point[data-index='6']")
    group_b.click(modifiers=["Control"])
    group_a = page.locator(".box--selected .box__point[data-index='5']")
    group_b = page.locator(".box--selected .box__point[data-index='6']")
    expect(group_a).to_have_attribute("aria-pressed", "true")
    expect(group_b).to_have_attribute("aria-pressed", "true")
    rect = group_a.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 6, rect["y"] + rect["height"] / 2 + 4, steps=3)
    page.mouse.up()
    group_a_after = page.locator(".box--selected .box__point[data-index='5']").get_attribute("style")
    group_b_after = page.locator(".box--selected .box__point[data-index='6']").get_attribute("style")
    assert group_a_after != group_a_before and group_b_after != group_b_before
    page.locator("[data-role='undo']").click()
    assert page.locator(".box--selected .box__point[data-index='5']").get_attribute("style") == group_a_before
    assert page.locator(".box--selected .box__point[data-index='6']").get_attribute("style") == group_b_before
    page.locator("[data-role='redo']").click()
    assert page.locator(".box--selected .box__point[data-index='5']").get_attribute("style") == group_a_after
    assert page.locator(".box--selected .box__point[data-index='6']").get_attribute("style") == group_b_after

    single = page.locator(".box--selected .box__point[data-index='1']")
    single_before = single.get_attribute("style")
    opposite = page.locator(".box--selected .box__point[data-index='14']")
    opposite_before = opposite.get_attribute("style")
    rect = single.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.keyboard.down("Shift")
    page.mouse.move(rect["x"] + rect["width"] / 2 + 4, rect["y"] + rect["height"] / 2 + 3, steps=3)
    page.keyboard.up("Shift")
    page.mouse.up()
    assert page.locator(".box--selected .box__point[data-index='14']").get_attribute("style") != opposite_before
    point_one = page.locator(".box--selected .box__point[data-index='1']")
    point_one.dblclick()
    assert page.locator(".box--selected .box__point[data-index='1']").get_attribute("style") == single_before

    invalid = page.locator(".box--selected .box__point[data-index='5']")
    invalid_rect = invalid.bounding_box()
    box_rect = page.locator(".box--selected").bounding_box()
    assert invalid_rect and box_rect
    invalid_before = invalid.get_attribute("style")
    page.mouse.move(invalid_rect["x"] + invalid_rect["width"] / 2, invalid_rect["y"] + invalid_rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(box_rect["x"] + 1, box_rect["y"] + box_rect["height"] - 1, steps=4)
    expect(page.locator("[data-role='banners']")).to_contain_text("вырожденную ячейку")
    page.mouse.up()
    assert page.locator(".box--selected .box__point[data-index='5']").get_attribute("style") == invalid_before
    apply_edits = page.locator("[data-role='apply-edits']")
    expect(apply_edits).to_be_visible()
    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ) as saved:
        apply_edits.click()
    payload = saved.value.request.post_data_json["document"]
    region = payload["regions"][0]
    assert region["style"]["warp"]["kind"] == "mesh"
    assert region["style"]["warp"]["version"] == 2
    expect(apply_edits).to_be_hidden()



@pytest.mark.ui
def test_mesh_context_loss_restores_exact_preview(page, desktop):
    """При потере WebGL черновой слой уступает точному серверному preview."""
    Image.new("RGB", (320, 180), "white").save(desktop.image)
    _open_and_translate(page)
    page_id = page.locator("[data-role='page-list'] [data-page-id]").get_attribute("data-page-id")
    assert page_id
    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ):
        page.evaluate("""async id => {
          const state = await import('/js/state.js');
          state.editDocument(document => { document.regions[0].bbox = [50, 40, 200, 80]; });
        }""", page_id)
    card = page.locator("[data-role='region-list'] .region-card").filter(has_text="Hello").first
    card.get_by_text("Hello", exact=True).click()
    card.locator("[data-region-tab='transform']").click()
    with page.expect_response(
        lambda response: "/preview-region" in response.url and response.request.method == "POST" and response.ok
    ):
        card.locator("[data-card-warp='mesh']").click()
    canvas = page.locator("[data-role='mesh-preview']")
    page.wait_for_function(
        "document.querySelector('[data-role=mesh-preview]')?.dataset.ready === 'true'",
        timeout=10_000,
    )
    point = page.locator(".box--selected .box__point[data-index='10']")
    rect = point.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 5, rect["y"] + rect["height"] / 2 + 3, steps=2)
    expect(canvas).to_be_visible()
    page.evaluate("""() => {
      const canvas = document.querySelector('[data-role="mesh-preview"]');
      const gl = canvas.getContext('webgl');
      const extension = gl && gl.getExtension('WEBGL_lose_context');
      if (!extension) throw new Error('WEBGL_lose_context недоступен');
      extension.loseContext();
    }""")
    expect(canvas).to_be_hidden()
    expect(page.locator("[data-role='style-preview']")).to_be_visible()
    expect(page.locator("[data-role='banners']")).to_contain_text("WebGL-контекст потерян")
    page.evaluate("""async () => {
      const canvas = document.querySelector('[data-role="mesh-preview"]');
      const gl = canvas.getContext('webgl');
      const extension = gl && gl.getExtension('WEBGL_lose_context');
      if (!extension) return;
      const restored = new Promise(resolve => canvas.addEventListener('webglcontextrestored', resolve, { once: true }));
      extension.restoreContext();
      await Promise.race([restored, new Promise(resolve => setTimeout(resolve, 1000))]);
    }""")
    page.mouse.up()


@pytest.mark.ui
def test_mesh_drag_cancels_on_escape_and_pointercancel(page, desktop):
    """Esc и pointercancel отменяют только текущий mesh-жест."""
    Image.new("RGB", (320, 180), "white").save(desktop.image)
    _open_and_translate(page)
    page_id = page.locator("[data-role='page-list'] [data-page-id]").get_attribute("data-page-id")
    assert page_id
    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ):
        page.evaluate("""async id => {
          const { editDocument } = await import('/js/state.js');
          editDocument(document => { document.regions[0].bbox = [50, 40, 200, 80]; });
        }""", page_id)
    regions = page.locator("[data-role='region-list']")
    regions.get_by_text("Hello", exact=True).click()
    card = regions.locator(".region-card--selected")
    card.locator("[data-region-tab='transform']").click()
    with page.expect_response(
        lambda response: "/preview-region" in response.url and response.request.method == "POST" and response.ok
    ):
        card.locator("[data-card-warp='mesh']").click()
    point = page.locator(".box--selected .box__point[data-index='5']")
    expect(point).to_be_visible()
    before = point.get_attribute("style")
    rect = point.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 8, rect["y"] + rect["height"] / 2 + 5, steps=3)
    page.keyboard.press("Escape")
    page.mouse.up()
    assert point.get_attribute("style") == before

    page.evaluate("""() => {
      const frame = document.querySelector('[data-role="frame"]');
      frame.addEventListener('pointerdown', event => { window.__iltMeshPointerId = event.pointerId; }, { once: true });
    }""")
    rect = point.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 8, rect["y"] + rect["height"] / 2 + 5, steps=3)
    pointer_id = page.evaluate("window.__iltMeshPointerId")
    page.locator("[data-role='frame']").evaluate(
        "(node, id) => node.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerId: id }))",
        pointer_id,
    )
    page.mouse.up()
    assert point.get_attribute("style") == before


@pytest.mark.ui
def test_text_layer_moves_without_changing_recognition_box(page):
    """Текст двигается отдельно, жест сохраняется одним шагом истории."""
    _open_and_translate(page)
    regions = page.locator("[data-role='region-list']")
    regions.get_by_text("Hello", exact=True).click()
    card = regions.locator(".region-card--selected")
    card.locator("[data-region-tab='transform']").click()
    card.locator("[data-region-action='text-move']").click()
    box = page.locator(".box--selected")
    rect = box.bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 20, rect["y"] + rect["height"] / 2, steps=2)
    page.keyboard.press("Escape")
    page.mouse.up()
    expect(page.locator("[data-role='undo']")).to_be_disabled()

    page.evaluate("""() => {
      const frame = document.querySelector('[data-role="frame"]');
      frame.addEventListener('pointerdown', event => { window.__iltPointerId = event.pointerId; }, { once: true });
    }""")
    expect(box).to_be_visible()
    rect = page.locator(".box--selected").bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 20, rect["y"] + rect["height"] / 2, steps=2)
    pointer_id = page.evaluate("window.__iltPointerId")
    page.locator("[data-role='frame']").evaluate(
        "(node, id) => node.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerId: id }))",
        pointer_id,
    )
    page.mouse.up()
    expect(page.locator("[data-role='undo']")).to_be_disabled()

    expect(box).to_be_visible()
    rect = page.locator(".box--selected").bounding_box()
    assert rect
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.mouse.down()
    page.mouse.move(rect["x"] + rect["width"] / 2 + 60, rect["y"] + rect["height"] / 2 + 20, steps=3)
    page.mouse.up()

    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ) as saved:
        page.wait_for_timeout(750)
    payload = saved.value.request.post_data_json["document"]
    moved = payload["regions"][0]
    assert moved["bbox"] == [0, 0, 8, 8]
    assert moved["text_position"] is not None
    assert moved["text_position"] != [4.0, 4.0]
    assert payload.get("strokes", []) == []
    expect(page.locator("[data-role='undo']")).to_be_enabled()

    with page.expect_response(
        lambda response: "/document" in response.url and response.request.method == "PUT" and response.ok
    ) as undone:
        page.locator("[data-role='undo']").click()
    restored = undone.value.request.post_data_json["document"]["regions"][0]
    assert restored["text_position"] is None


@pytest.mark.ui
def test_done_requests_layout_snapshot_when_preview_never_arrives(page, desktop):
    """Done не зависит от завершения preview: snapshot приходит отдельным API."""
    Image.new("RGB", (320, 180), "white").save(desktop.image)
    _open_and_translate(page)
    page_id = page.locator("[data-role='page-list'] [data-page-id]").get_attribute("data-page-id")
    assert page_id
    page.route("**/api/pages/*/preview-region", lambda route: route.abort())
    page.locator("[data-role='region-list']").get_by_text("Hello", exact=True).click()
    page.evaluate("""async () => {
      const state = await import('/js/state.js');
      state.editDocument(document => {
        const region = document.regions[0];
        region.bbox = [50, 40, 200, 80];
        region.layout_snapshot = null;
        region.style.rotation = 35;
        region.style.warp = {kind: 'arc', bend: 0.3};
      }, {deferApply: true});
    }""")
    assert page.evaluate("""async () => {
      const state = await import('/js/state.js');
      return state.getState().document.regions[0].layout_snapshot;
    }""") is None
    apply_edits = page.locator("[data-role='apply-edits']")
    expect(apply_edits).to_be_visible()
    with page.expect_response(
        lambda response: "/layout-snapshot" in response.url
        and response.request.method == "POST"
    ) as snapshot_response:
        with page.expect_response(
            lambda response: "/document" in response.url
            and response.request.method == "PUT"
            and response.ok
        ) as saved:
            apply_edits.click()
    snapshot_payload = snapshot_response.value.json()
    assert snapshot_payload["layout_snapshot"], {
        "response": snapshot_payload,
        "request": snapshot_response.value.request.post_data_json,
    }
    region = saved.value.request.post_data_json["document"]["regions"][0]
    assert region["layout_snapshot"]["version"] == 1
    assert region["layout_snapshot"]["lines"]
    expect(apply_edits).to_be_hidden()


@pytest.mark.ui
def test_web_retry_after_terminal_bake_error_requests_rebake_once(page):
    """Второй Done после ошибки ставит адресный rebake, а не второй PUT."""
    _open_and_translate(page)
    page_id = page.locator("[data-role='page-list'] [data-page-id]").get_attribute("data-page-id")
    assert page_id
    page.locator("[data-role='region-list']").get_by_text("Hello", exact=True).click()
    page.evaluate("""async () => {
      const state = await import('/js/state.js');
      state.editDocument(document => {
        document.regions[0].style.warp = {kind: 'wave', bend: 0.2};
      }, {deferApply: true});
    }""")
    state = {"fail": True}
    rebakes = []
    puts = []
    page.on(
        "request",
        lambda request: puts.append(1)
        if request.method == "PUT" and "/document" in request.url
        else None,
    )

    def page_route(route):
        if state["fail"]:
            route.fulfill(
                status=200,
                json={
                    "page": {"id": page_id},
                    "status": "error",
                    "error": "Не собралось",
                    "render_version": 0,
                },
            )
        else:
            route.continue_()

    def rebake_route(route):
        rebakes.append(1)
        state["fail"] = False
        route.fulfill(status=200, json={"job_id": "retry", "status": "queued"})

    page.route(f"**/api/pages/{page_id}", page_route)
    page.route(f"**/api/pages/{page_id}/rebake", rebake_route)
    apply_edits = page.locator("[data-role='apply-edits']")
    apply_edits.click()
    expect(apply_edits).to_be_visible()
    expect(page.locator("[data-role='banners']")).to_contain_text("Не собралось")
    assert len(puts) == 1
    assert rebakes == []

    apply_edits.click()
    expect(apply_edits).to_be_hidden()
    assert len(puts) == 1
    assert rebakes == [1]


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


def test_first_run_shows_preparation_estimate_for_selected_profile(page):
    plans = []
    starts = []

    def plan_route(route):
        plans.append(route.request.post_data_json)
        route.fulfill(status=200, json={
            "items": [{"id": "detector", "title": "Детектор", "ready": False, "download_bytes": 3 * 1024 * 1024}],
            "total": 3 * 1024 * 1024,
            "required_space": 12 * 1024 * 1024,
            "warnings": [],
        })

    def start_route(route):
        starts.append(1)
        route.fulfill(status=202, json={"state": "planning"})

    page.route("**/api/preparation/plan", plan_route)
    page.route("**/api/preparation/start", start_route)
    page.evaluate("""async () => {
      const bootstrap = await (await fetch('/api/bootstrap')).json();
      bootstrap.settings.first_run_complete = false;
      await fetch('/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(bootstrap.settings)});
    }""")
    page.reload()
    expect(page.locator("[data-role='screen-wizard']")).to_be_visible()
    page.locator("#wizard-next").click()
    page.locator("#wizard-next").click()
    expect(page.locator("[data-role='preparation-note']")).to_contain_text("3.0 МБ")
    expect(page.locator("[data-role='preparation-note']")).to_contain_text("12.0 МБ")
    expect(page.locator("[data-role='wizard-models']")).to_contain_text("Детектор")
    assert plans[-1]["translator_backend"] == "llm"
    assert starts == []

    page.locator("#wizard-prev").click()
    page.locator("#wizard-prev").click()
    page.locator("input[name='wiz-profile'][value='offline']").check()
    page.locator("#wizard-next").click()
    page.locator("#wizard-next").click()
    expect(page.locator("[data-role='preparation-note']")).to_contain_text("3.0 МБ")
    assert plans[-1]["translator_backend"] == "argos"


@pytest.mark.ui
def test_first_run_restores_paused_preparation_and_resumes_matching_profile(page):
    resumed = []
    page.route("**/api/preparation/plan", lambda route: route.fulfill(status=200, json={
        "items": [{"id": "detector", "title": "Детектор", "ready": False, "download_bytes": 1024}],
        "total": 1024,
        "required_space": 4096,
        "warnings": [],
    }))
    page.route("**/api/preparation", lambda route: route.fulfill(status=200, json={
        "state": "paused",
        "selection": {
            "source_lang": "en",
            "target_lang": "ru",
            "translator_backend": "llm",
            "inpainter_backend": "lama",
            "device": "auto",
            "models_dir": "",
        },
        "done": 512,
        "total": 2048,
        "current": "Детектор",
    }))

    def resume_route(route):
        resumed.append(route.request.method)
        route.fulfill(status=202, json={"state": "downloading", "done": 512, "total": 2048})

    page.route("**/api/preparation/resume", resume_route)
    page.evaluate("""async () => {
      const bootstrap = await (await fetch('/api/bootstrap')).json();
      bootstrap.settings.first_run_complete = false;
      await fetch('/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(bootstrap.settings)});
    }""")
    page.reload()
    expect(page.locator("[data-role='screen-wizard']")).to_be_visible()
    page.locator("#wizard-next").click()
    page.locator("#wizard-next").click()
    expect(page.locator("[data-role='preparation-note']")).to_contain_text("Подготовка приостановлена")
    resume = page.locator("[data-role='preparation-resume']")
    expect(resume).to_be_visible()
    with page.expect_response(lambda response: "/api/preparation/resume" in response.url and response.ok):
        resume.click()
    assert resumed == ["POST"]


@pytest.mark.ui
def test_first_run_shows_persisted_preparation_error(page):
    page.route("**/api/preparation/plan", lambda route: route.fulfill(status=200, json={
        "items": [{"id": "detector", "title": "Детектор", "ready": False, "download_bytes": 1024}],
        "total": 1024,
        "required_space": 4096,
        "warnings": [],
    }))
    page.route("**/api/preparation", lambda route: route.fulfill(status=200, json={
        "state": "error",
        "error": "Не удалось проверить целостность компонента",
        "error_kind": "integrity",
        "done": 1024,
        "total": 1024,
    }))
    page.evaluate("""async () => {
      const bootstrap = await (await fetch('/api/bootstrap')).json();
      bootstrap.settings.first_run_complete = false;
      await fetch('/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(bootstrap.settings)});
    }""")
    page.reload()
    expect(page.locator("[data-role='screen-wizard']")).to_be_visible()
    page.locator("#wizard-next").click()
    page.locator("#wizard-next").click()
    expect(page.locator("[data-role='preparation-note']")).to_contain_text("Не удалось проверить целостность компонента")
    expect(page.locator("[data-role='preparation-start']")).to_be_visible()
