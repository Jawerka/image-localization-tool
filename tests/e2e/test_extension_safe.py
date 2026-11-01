"""Регрессии безопасного выбора, результата отдельно от сайта и копий Пикабу."""
from __future__ import annotations

import subprocess
import sys
import json
import shutil
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

from test_extension import DIST, ROOT, SCRIPT, PAIR_CODE, _extension_id, _start_server

pytestmark = pytest.mark.ui


@pytest.fixture
def safe_extension(tmp_path):
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Chromium Playwright не установлен")
        subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)
        server, base = _start_server()
        # Headless не показывает диалог разрешений: сужаем host_permissions
        # до локального origin в копии сборки, production manifest не меняем.
        extension_dir = tmp_path / "extension"
        shutil.copytree(DIST, extension_dir)
        manifest_path = extension_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["host_permissions"] = ["http://127.0.0.1/*"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), headless=True, channel="chromium",
            ignore_default_args=["--disable-extensions"],
            args=[f"--disable-extensions-except={extension_dir.as_posix()}", f"--load-extension={extension_dir.as_posix()}",
                  "--disable-features=LocalNetworkAccessChecks"],
            viewport={"width": 1000, "height": 800},
        )
        try:
            extension_id = _extension_id(context)
            options = context.new_page()
            options.goto(f"chrome-extension://{extension_id}/options.html")
            options.locator("#server-url").fill(base)
            options.locator("#pair-code").fill(PAIR_CODE)
            options.locator("#pair").click()
            options.wait_for_function("() => document.querySelector('#status').textContent === 'сопряжено'")
            yield context, options, base, extension_id
        finally:
            context.close()
            server.shutdown()
            server.server_close()


def _tab_id(options, url):
    # В чистом профиле адрес вкладки скрыт до выдачи activeTab.
    return options.evaluate("async () => Math.max(...(await chrome.tabs.query({})).map(t=>t.id))")


def _start_select(options, tab_id):
    options.evaluate("async id => chrome.tabs.sendMessage(id, {type:'select-image'})", tab_id)


def _wait_done(page):
    result = page.locator("[data-ilt-result]")
    result.wait_for()
    page.wait_for_function("() => document.querySelector('[data-ilt-result]')?.dataset.state === 'done'")
    return result


def _geometry(page, selector="#pic"):
    return page.locator(selector).evaluate(
        "e => ({rect:e.getBoundingClientRect().toJSON(), parent:e.parentElement.getBoundingClientRect().toJSON()})"
    )


def test_inline_selection_and_optional_panel(safe_extension):
    context, options, base, extension_id = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.locator("#pic").wait_for()
    page.wait_for_function("() => document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    before_html = page.locator("#pic").evaluate("e=>e.outerHTML")
    before_geo = _geometry(page)
    page.wait_for_timeout(150)
    assert page.locator(".ilt-ui").count() == 0
    assert page.locator("#pic").evaluate("e=>e.outerHTML") == before_html

    _start_select(options, tab_id)
    page.mouse.move(200, 230)
    page.wait_for_function("() => document.querySelector('[popover]')?.matches(':popover-open')")
    page.keyboard.press("Escape")
    assert page.locator("[popover]").count() == 0
    page.evaluate("window.clicks=0; document.querySelector('#pic').addEventListener('click',()=>window.clicks++)")
    page.locator("#pic").click()
    assert page.evaluate("window.clicks") == 1

    _start_select(options, tab_id)
    page.locator("#pic").click()
    assert page.locator("[data-ilt-selector]").count() == 0
    assert page.evaluate("window.clicks") == 1
    result = _wait_done(page)
    assert result.get_attribute("data-state") == "done"
    assert result.get_by_role("button", name="Разрешить и перевести", exact=True).count() == 0
    assert result.locator("canvas").is_hidden()
    assert page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")
    assert _geometry(page) == before_geo
    compare = result.locator("button[aria-label='Сравнить']")
    compare.dispatch_event("pointerdown")
    assert page.locator("#pic").evaluate("e=>e.outerHTML") == before_html
    compare.dispatch_event("pointerup")
    page.wait_for_function("() => document.querySelector('#pic').currentSrc.startsWith('blob:')")
    assert _geometry(page) == before_geo
    page.locator("#pic").click()
    assert page.evaluate("window.clicks") == 2
    result.locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    assert page.locator("[data-ilt-result][data-state='done']").count() == 0
    assert page.locator("#pic").evaluate("e=>e.outerHTML") == before_html
    assert _geometry(page) == before_geo


def test_dynamic_dialog_canvas_background_and_disabled_hover(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    tab_id = _tab_id(options, page.url)
    page.evaluate("""base => {
      document.documentElement.style.transform='translateX(9px)';
      document.querySelector('#lightbox').innerHTML='<img id="dynamic" style="width:240px;height:240px" src="'+base+'/pic.png">';
      document.querySelector('#lightbox').showModal();
    }""", base)
    _start_select(options, tab_id)
    page.locator("#dynamic").hover()
    assert page.locator("[data-ilt-selector]").evaluate("e=>e.matches(':popover-open')")
    page.locator("#dynamic").click()
    geo = page.locator("#dynamic").evaluate("e=>e.getBoundingClientRect().toJSON()")
    _wait_done(page)
    assert page.locator("[data-ilt-result] canvas").is_hidden()
    assert page.locator("#dynamic").evaluate("e=>e.getBoundingClientRect().toJSON()") == geo
    page.locator("[data-ilt-result]").locator("button[aria-label='Сравнить']").dispatch_event("pointerdown")
    assert page.locator("#dynamic").evaluate("e=>!e.currentSrc.startsWith('blob:')")
    page.locator("[data-ilt-result]").locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    page.evaluate("() => { document.querySelector('#lightbox').close(); document.documentElement.style.transform=''; }")
    assert not page.locator("#lightbox").evaluate("e=>e.open")
    page.evaluate("""() => {
      const canvas=document.createElement('canvas'); canvas.id='canvas';canvas.width=240;canvas.height=200;
      canvas.style.cssText='position:fixed;left:500px;top:10px';
      canvas.getContext('2d').fillRect(0,0,240,200);document.body.append(canvas);
    }""")
    _start_select(options, tab_id)
    page.locator("#canvas").click()
    options.wait_for_function("""async id => {
      const result=await chrome.runtime.sendMessage({type:'get-selection',tabId:id});
      return result?.imageUrl.startsWith('data:image/png');
    }""", arg=tab_id)
    page.locator("[data-ilt-result] canvas").wait_for(state="visible")
    page.locator("[data-ilt-result]").locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    page.evaluate("() => {document.querySelector('#canvas').toDataURL=()=>{throw new DOMException('tainted','SecurityError')};}")
    _start_select(options, tab_id)
    page.locator("#canvas").click()
    options.wait_for_function("""async id => {
      const result=await chrome.runtime.sendMessage({type:'get-selection',tabId:id});
      return result?.error.includes('защищён');
    }""", arg=tab_id)
    page.locator("[data-ilt-result]").locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    assert page.locator("[data-ilt-selector]").count() == 0
    page.evaluate("""base => {
      const div=document.createElement('div');div.id='background';
      div.style.cssText='position:fixed;left:500px;top:250px;width:240px;height:200px;background-image:url('+base+'/pic.png)';
      document.body.append(div);
    }""", base)
    _start_select(options, tab_id)
    page.locator("#background").click()
    options.wait_for_function("""async id => {
      const result=await chrome.runtime.sendMessage({type:'get-selection',tabId:id});
      return result?.imageUrl.endsWith('/pic.png');
    }""", arg=tab_id)
    page.locator("[data-ilt-result] canvas").wait_for(state="visible")
    page.locator("[data-ilt-result]").locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    options.locator("#hover-disabled-sites").fill("127.0.0.1")
    options.locator("#hover-disabled-sites").blur()
    page.reload()
    page.wait_for_timeout(150)
    assert page.locator(".ilt-ui").count() == 0


def test_saved_pikabu_has_no_idle_changes(safe_extension):
    context, _, _, _ = safe_extension
    files = sorted((ROOT / "test-img" / "html").glob("*.html"))
    files = [file for file in files if "страница 2" in file.name or "страница 3" in file.name]
    if not files:
        pytest.skip("Локальные копии Пикабу отсутствуют")
    for file in files:
        page = context.new_page()
        # Сеть отключена: проверяется сохранённая разметка, а не живой Пикабу.
        page.route("**/*", lambda route: route.abort() if route.request.resource_type == "script" or route.request.url.startswith(("http:", "https:")) else route.continue_())
        # Сохранённые inline-скрипты могут ждать отсутствующую сеть. Для
        # детерминированной проверки layout используем HTML/CSS/локальные ресурсы.
        raw = file.read_bytes()
        encoding = "utf-8" if b'charset="utf-8"' in raw[:2000].lower() else "cp1251"
        html = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", raw.decode(encoding), flags=re.S | re.I)
        html = html.replace("<head>", '<head><base href="' + file.as_uri() + '">', 1)
        page.goto(file.as_uri(), wait_until="commit")
        page.set_content(html, wait_until="domcontentloaded")
        page.wait_for_timeout(200)
        # file-доступ расширения отключён в чистом профиле: подключаем тот же код вручную.
        before = page.evaluate("document.documentElement.outerHTML")
        geometry = page.locator("img").evaluate_all("es=>es.map(e=>({src:e.src,rect:e.getBoundingClientRect().toJSON()}))")
        page.evaluate("""() => {
          window.chrome = {
            runtime: {onMessage: {addListener() {}}},
            storage: {local: {get(keys, callback) {callback({});}}}
          };
        }""")
        for name in ("button-model.js", "log.js", "inline-content.js", "safe-content.js"):
            page.add_script_tag(content=(ROOT / "extension/src" / name).read_text(encoding="utf-8"))
        page.wait_for_timeout(100)
        # add_script_tag сам добавляет два тега; удаляем их перед сравнением.
        page.evaluate("document.querySelectorAll('script:not([src])').forEach(e=>{const t=e.textContent; if(t.includes('iltSafeContent')||t.includes('iltInlineContent')||t.includes('iltButtonModel')||t.includes('iltLog')) e.remove()})")
        assert page.evaluate("document.documentElement.outerHTML") == before
        assert page.locator("img").evaluate_all("es=>es.map(e=>({src:e.src,rect:e.getBoundingClientRect().toJSON()}))") == geometry
        page.close()


def test_inline_picture_scroll_resize_source_and_removal(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.evaluate("""() => {
      const img=document.querySelector('#pic'), picture=document.createElement('picture');
      img.before(picture); picture.append(img);
      const source=document.createElement('source');source.srcset=img.src;picture.prepend(source);
    }""")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    before = page.locator("picture").evaluate("e=>e.outerHTML")
    before_geo = _geometry(page)
    count = len(context.pages)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    result = _wait_done(page)
    assert len(context.pages) == count
    assert page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")
    assert page.locator("source").evaluate("e=>e.srcset.startsWith('blob:')")
    assert _geometry(page) == before_geo
    page.evaluate("scrollTo(0, 70)")
    page.set_viewport_size({"width": 1100, "height": 850})
    page.evaluate("document.querySelector('#contain').style.width='360px'")
    page.wait_for_timeout(80)
    assert abs(_geometry(page)["rect"]["width"] - 360) < 2
    page.evaluate("document.querySelector('source').srcset='/pic.png?changed=1'")
    result.wait_for(state="detached")
    assert page.locator("picture").evaluate("e=>e.outerHTML") != before
    _start_select(options, tab_id)
    page.locator("#pic").click()
    page.locator("[data-ilt-result]").wait_for()
    page.locator("#contain").evaluate("e=>e.remove()")
    page.locator("[data-ilt-result]").wait_for(state="detached")


def test_inline_context_target_duplicate_url_and_modal_move(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    # На странице уже два img с одним URL: выбор хранит именно DOM-цель ПКМ.
    page.locator("#pic").click(button="right")
    response = options.evaluate("""async value => chrome.tabs.sendMessage(value.id,
      {type:'translate-inline',imageUrl:value.url,permitted:true})""", {"id":tab_id,"url":base+"/pic.png"})
    assert response["ok"]
    result = _wait_done(page)
    assert result.locator("canvas").is_hidden()
    page.locator("#open-lightbox").click()
    page.wait_for_function("document.querySelector('#lightbox [data-ilt-result]') !== null")
    result.locator("button[aria-label='Сравнить']").dispatch_event("pointerdown")
    assert page.locator("#pic").evaluate("e=>!e.currentSrc.startsWith('blob:')")
    result.locator("button[aria-label='Сравнить']").dispatch_event("pointerup")
    page.wait_for_function("() => document.querySelector('#pic').currentSrc.startsWith('blob:')")
    page.evaluate("document.querySelector('#lightbox').close()")
    page.wait_for_function("document.querySelector('#lightbox [data-ilt-result]') === null")
    assert page.evaluate("""() => {
      const panel = document.querySelector('[data-ilt-result]').shadowRoot.querySelector('.panel');
      return panel.hidden || panel.classList.contains('off');
    }""")


def test_inline_error_retry_permission_and_csp(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/csp.html")
    tab_id = _tab_id(options, page.url)
    original = page.locator("#pic").evaluate("e=>e.outerHTML")
    options.evaluate("chrome.storage.local.set({token:''})")
    _start_select(options, tab_id)
    page.locator("#pic").click()
    result = page.locator("[data-ilt-result]")
    result.locator("[role='status']").get_by_text("нет ключа сопряжения").wait_for()
    assert result.locator("canvas").is_hidden()
    options.locator("#pair-code").fill(PAIR_CODE)
    options.locator("#pair").click()
    options.wait_for_function("document.querySelector('#status').textContent === 'сопряжено'")
    result.get_by_role("button", name="Повторить", exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-ilt-result]')?.dataset.state === 'done'")
    swapped = page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")
    if swapped:
        assert result.locator("canvas").is_hidden()
    else:
        result.locator("canvas").wait_for(state="visible")
        assert page.locator("#pic").evaluate("e=>e.outerHTML") == original
    result.locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    assert page.locator("#pic").evaluate("e=>e.outerHTML") == original


def test_inline_permission_button_uses_user_gesture(safe_extension):
    context, options, base, _ = safe_extension
    # Имитируем неизвестное разрешение; сам локальный origin уже выдан
    # тестовым manifest, поэтому Chromium не открывает headless-диалог.
    worker = context.service_workers[0]
    worker.evaluate("chrome.permissions.contains = async () => false")
    page = context.new_page()
    page.goto(base + "/page.html")
    tab_id = _tab_id(options, page.url)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    result = page.locator("[data-ilt-result]")
    result.get_by_role("button", name="Разрешить и перевести", exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-ilt-result]')?.dataset.state === 'done'")
    assert result.get_attribute("data-state") == "done"


def test_inline_drops_late_result_when_source_changes(safe_extension):
    context, options, base, _ = safe_extension
    worker = context.service_workers[0]
    # Задерживаем сеть воркера, чтобы сменить картинку до готового ответа.
    worker.evaluate("""() => {
      const original=globalThis.fetch;
      globalThis.fetch=async (...args) => {
        if (String(args[0]).includes('/result')) await new Promise(r=>setTimeout(r,900));
        return original(...args);
      };
    }""")
    page = context.new_page()
    page.goto(base + "/page.html")
    tab_id = _tab_id(options, page.url)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    result = page.locator("[data-ilt-result]")
    result.wait_for()
    page.locator("#pic").evaluate("e=>e.src='/pic.png?new-page=1'")
    result.wait_for(state="detached")
    options.wait_for_function("""async selection => {
      const status=await chrome.runtime.sendMessage({type:'get-status',...selection});
      return status.status==='done';
    }""", arg={"imageUrl":base+"/pic.png","pageUrl":base+"/page.html"})
    assert page.locator("[data-ilt-result]").count() == 0


def test_manual_selection_only_top_frame(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    tab_id = _tab_id(options, page.url)
    page.evaluate("""base => {
      const frame=document.createElement('iframe');frame.id='nested';
      frame.src=base+'/page.html?nested=1';
      frame.style.cssText='position:fixed;left:0;top:0;width:600px;height:500px;border:0';
      document.body.append(frame);
    }""", base)
    nested = page.frame_locator("#nested")
    nested.locator("#pic").wait_for(state="visible")
    # Content script во фрейме подписывается на сообщения после storageGet.
    page.wait_for_timeout(300)
    _start_select(options, tab_id)
    page.locator("[data-ilt-selector]").wait_for()
    assert nested.locator("[data-ilt-selector]").count() == 0
    page.keyboard.press("Escape")
    page.locator("[data-ilt-selector]").wait_for(state="detached")


def test_hover_button_inside_image_without_layout_shift(safe_extension):
    context, _, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    assert page.locator("[data-ilt-hover]").count() == 0
    before = page.evaluate("""() => {
      const img=document.querySelector('#pic'), contain=document.querySelector('#contain');
      return {img:img.getBoundingClientRect().toJSON(), contain:contain.getBoundingClientRect().toJSON(),
        html:img.outerHTML};
    }""")
    page.locator("#pic").hover()
    button = page.locator("[data-ilt-hover] button.face")
    button.wait_for(state="visible")
    after = page.evaluate("""() => {
      const img=document.querySelector('#pic'), contain=document.querySelector('#contain');
      return {img:img.getBoundingClientRect().toJSON(), contain:contain.getBoundingClientRect().toJSON(),
        html:img.outerHTML};
    }""")
    assert after == before
    assert page.locator("#contain [data-ilt-hover]").count() == 0
    box = button.evaluate("e=>e.getBoundingClientRect().toJSON()")
    image = after["img"]
    assert box["left"] >= image["left"] and box["top"] >= image["top"]
    assert box["right"] <= image["right"] and box["bottom"] <= image["bottom"]
    button.click()
    _wait_done(page)
    page.mouse.move(5, 5)
    page.wait_for_function("""() => {
      const face=document.querySelector('[data-ilt-result]').shadowRoot.querySelector('button.face');
      return getComputedStyle(face).opacity === '0';
    }""", timeout=3000)
    opacity = """selector => {
      const root=document.querySelector('[data-ilt-result]').shadowRoot;
      return getComputedStyle(root.querySelector(selector)).opacity;
    }"""
    page.evaluate("document.querySelector('#contain').style.width='720px'")
    page.locator("#pic").hover()
    page.wait_for_function(f"() => ({opacity})('button.face') === '1'", timeout=3000)
    assert page.evaluate(opacity, ".panel") == "0"
    face_box = button.evaluate("e=>e.getBoundingClientRect().toJSON()")
    page.mouse.move(face_box["left"] + 16, face_box["top"] + 16)
    page.wait_for_function(f"() => ({opacity})('.panel') === '1'", timeout=3000)
    panel = page.locator("[data-ilt-result] .panel")
    panel_box = panel.evaluate("e=>e.getBoundingClientRect().toJSON()")
    assert abs(panel_box["top"] - face_box["top"]) < 1
    assert panel_box["right"] <= face_box["left"]
    pic_box = page.locator("#pic").evaluate("e=>e.getBoundingClientRect().toJSON()")
    page.mouse.move(pic_box["left"] + 20, pic_box["bottom"] - 20)
    page.wait_for_function(f"() => ({opacity})('.panel') === '0'", timeout=3000)
    assert page.evaluate(opacity, "button.face") == "1"
    page.locator("[data-ilt-result]").locator("button[aria-label='Убрать']").evaluate("e => e.click()")
    page.mouse.move(5, 5)
    page.locator("#pic").hover()
    button.wait_for(state="visible")
    page.locator("#chrome").hover()
    page.wait_for_timeout(400)
    assert button.is_hidden()
    page.evaluate("""base => {
      const a=document.createElement('a');a.id='linked';a.href='#';
      a.style.cssText='position:fixed;left:500px;top:20px;display:block;width:220px;height:220px';
      const img=document.createElement('img');img.id='linked-pic';img.src=base+'/pic.png';
      img.style.cssText='width:100%;height:100%';a.append(img);document.body.append(a);
    }""", base)
    page.wait_for_function("document.querySelector('#linked-pic').complete")
    page.locator("#linked-pic").hover()
    button.wait_for(state="visible")
    assert page.locator("#linked-pic").evaluate("e=>e.parentElement.tagName") == "A"
    page.locator("#open-lightbox").click()
    page.locator("#pic").hover()
    button.wait_for(state="visible")
    page.wait_for_function("document.querySelector('#lightbox [data-ilt-hover]') !== null")


def test_result_controls_inside_image_and_fade(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    before = page.locator("#pic").evaluate("e=>e.getBoundingClientRect().toJSON()")
    _start_select(options, tab_id)
    page.locator("#pic").click()
    result = _wait_done(page)
    assert result.locator("canvas").is_hidden()
    face = result.locator("button.face")
    face.wait_for(state="visible")
    assert page.locator("#pic").evaluate("e=>e.getBoundingClientRect().toJSON()") == before
    image = page.locator("#pic").evaluate("e=>e.getBoundingClientRect().toJSON()")
    box = face.evaluate("e=>e.getBoundingClientRect().toJSON()")
    assert box["left"] >= image["left"] and box["top"] >= image["top"]
    assert box["right"] <= image["right"] and box["bottom"] <= image["bottom"]


def test_inline_srcset_2x_keeps_layout(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.evaluate("e => { const img=document.querySelector('#pic'); img.srcset=e+'/pic.png 2x'; }", base)
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    before = _geometry(page)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    assert _geometry(page) == before
    assert page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")


def test_inline_site_restore_and_new_url_cache(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    original = base + "/pic.png"
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    page.locator("#pic").evaluate("(e, url) => { e.src = url; }", original)
    page.wait_for_function("() => document.querySelector('#pic').currentSrc.startsWith('blob:')")
    page.locator("#pic").evaluate("(e, url) => { e.removeAttribute('srcset'); e.src = url; }", original + "?next=1")
    page.locator("[data-ilt-result]").wait_for(state="detached")
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    page.locator("#pic").evaluate("(e, url) => { e.removeAttribute('srcset'); e.src = url; }", original)
    page.wait_for_function("() => document.querySelector('[data-ilt-result]') && document.querySelector('#pic').currentSrc.startsWith('blob:')")


def test_inline_hover_overlay_keeps_translation(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    page.evaluate("""() => {
      const cover=document.createElement('div');
      cover.id='hover-cover';
      cover.style.cssText='position:absolute;inset:0;background:linear-gradient(#0000,#0006)';
      document.querySelector('#contain').append(cover);
    }""")
    page.locator("#hover-cover").hover()
    page.wait_for_timeout(80)
    assert page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")
    assert page.locator("[data-ilt-result]").count() == 1


def test_inline_pushstate_keeps_translation(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    page.evaluate("history.pushState({}, '', '/page.html?view=1')")
    page.wait_for_timeout(50)
    assert page.locator("[data-ilt-result]").count() == 1
    assert page.locator("#pic").evaluate("e=>e.currentSrc.startsWith('blob:')")


def test_inline_save_translation_download(safe_extension):
    context, options, base, _ = safe_extension
    page = context.new_page()
    page.goto(base + "/page.html")
    page.wait_for_function("document.querySelector('#pic').complete")
    tab_id = _tab_id(options, page.url)
    _start_select(options, tab_id)
    page.locator("#pic").click()
    _wait_done(page)
    worker = context.service_workers[0]
    downloads = worker.evaluate("""async args => {
      globalThis.__iltDownloads = [];
      chrome.downloads.download = async options => { globalThis.__iltDownloads.push(options); return 1; };
      const tabs = await chrome.tabs.query({});
      const tab = tabs.find(item => item.id === args.tabId) || tabs.at(-1);
      await iltOnContextMenuClick({menuItemId:'ilt-save-translation', srcUrl: args.src, frameId: 0}, tab);
      for (let i = 0; i < 40 && !globalThis.__iltDownloads.length; i += 1) {
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      return globalThis.__iltDownloads;
    }""", {"tabId": tab_id, "src": base + "/pic.png"})
    assert downloads and downloads[0]["filename"].endswith(".ru.png")
    assert downloads[0]["saveAs"] is True
