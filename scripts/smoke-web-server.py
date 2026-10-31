"""Реальная обработка, правка и скачивание через опубликованный браузерный API."""

import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--username", default="")
    parser.add_argument("--password-file", default="")
    parser.add_argument("--out", default="build/web-server-smoke")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    username = args.username.strip()
    password = ""
    if args.password_file:
        password = Path(args.password_file).read_text(encoding="utf-8-sig").strip()
    if bool(username) != bool(password):
        raise SystemExit("Логин и --password-file задаются вместе")
    base = args.url.rstrip("/")
    session = requests.Session()
    session.trust_env = False

    def call(method, path, body=None, **kwargs):
        response = session.request(method, base + path, json=body, timeout=90, **kwargs)
        if not response.ok:
            raise RuntimeError(f"{path}: HTTP {response.status_code}: {response.text[:500]}")
        return response

    def wait_job(job_id):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = call("GET", f"/api/jobs/status?job_id={job_id}").json()
            if result["status"] == "done":
                return result
            if result["status"] in {"error", "cancelled"}:
                raise RuntimeError(str(result))
            time.sleep(0.5)
        raise TimeoutError(job_id)

    if username:
        assert session.get(base + "/api/bootstrap", timeout=10).status_code == 401
        call("POST", "/api/session", {"username": username, "password": password})
    else:
        assert session.get(base + "/api/bootstrap", timeout=10).status_code == 200
    assert session.get(base + "/api/bootstrap", headers={"Origin": "http://evil.invalid"}, timeout=10).status_code == 403
    bootstrap = call("GET", "/api/bootstrap").json()
    assert bootstrap["capabilities"]["browser_files"]
    assert bootstrap["settings"]["device"] == "cpu"
    image = Image.new("RGB", (640, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 40, 600, 360), outline="black", width=4)
    draw.multiline_text((175, 145), "Hello world!\nHow are you?", fill="black", spacing=10,
                        font=ImageFont.load_default(size=40))
    image.save(root / "source.png")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    uploaded = call("POST", "/api/browser/upload?name=smoke-page.png", data=buffer.getvalue(),
                    headers={"Content-Type": "application/octet-stream"}).json()
    page_id = uploaded["pages"][-1]["id"]
    print("Uploaded; real translation...", flush=True)
    wait_job(call("POST", "/api/jobs/translate", {"scope": "page", "page_id": page_id}).json()["job_id"])
    detail = call("GET", f"/api/pages/{page_id}").json()
    document = detail["document"]
    assert any(region.get("translation") for region in document["regions"])
    document["regions"][0]["translation"] = "Проверка браузерного редактора"
    call("PUT", f"/api/pages/{page_id}/document", {"base_version": document["version"], "document": document})
    result = call("POST", "/api/browser/export", {"page_ids": [page_id]}).json()
    wait_job(result["job_id"])
    archive = call("GET", result["download_url"]).content
    (root / "translated-pages.zip").write_bytes(archive)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        pngs = [name for name in zipped.namelist() if name.lower().endswith(".png")]
        assert pngs
        output = zipped.read(pngs[0])
        Image.open(io.BytesIO(output)).verify()
        (root / "result.png").write_bytes(output)
    package = call("POST", "/api/browser/project", {"editor": {}}).json()
    content = call("GET", package["download_url"]).content
    assert zipfile.is_zipfile(io.BytesIO(content))
    (root / "project.ilt.zip").write_bytes(content)
    report = {"ok": True, "url": base, "project_id": uploaded["project"]["id"],
              "page_id": page_id, "export_url": result["download_url"], "package_url": package["download_url"]}
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.browser:
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            if username:
                page.get_by_label("Логин", exact=True).fill(username)
                page.locator("input[name='password']").fill(password)
                page.get_by_role("button", name="Войти", exact=True).click()
            expect(page.locator("[data-role='screen-error']")).to_be_hidden()
            expect(page.locator("[data-role='page-list']")).to_contain_text("smoke-page.png")
            page.locator("[data-role='export']:visible").click()
            with page.expect_download(timeout=120000) as downloaded:
                page.locator("[data-role='export-go']").click()
            assert downloaded.value.failure() is None
            expect(page.get_by_role("button", name="Скачать ZIP", exact=True)).to_be_visible()
            page.screenshot(path=str(root / "browser.png"), full_page=True)
            assert errors == []
            browser.close()
    session.close()
    print("Real browser server: upload, pipeline, edit, ZIP, project package OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
