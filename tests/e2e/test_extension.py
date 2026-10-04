"""Смоук unpacked-расширения: локальный /v1 и Playwright Chromium.

Без Playwright или без скачанного Chromium тест пропускается.
Быстрый набор его не запускает: маркер ui.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.ui

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-extension.py"
DIST = ROOT / "dist" / "chromium"
TOKEN = "ilt-test-token"
PAIR_CODE = "000000"


class ApiHandler(BaseHTTPRequestHandler):
    """Минимальный /v1: код 000000, перевод сразу done, PNG в ответе."""

    jobs: dict = {}
    events: list = []
    lock = threading.Lock()
    seq = 0
    page_png = b""
    result_png = b""

    def log_message(self, fmt: str, *args) -> None:
        return

    def _path(self) -> str:
        return urllib.parse.urlsplit(self.path).path

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _bearer(self) -> str:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:].strip()
        return ""

    def _cors(self) -> None:
        requested = self.headers.get("Access-Control-Request-Headers")
        allow = requested or "Authorization, Content-Type"
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", allow)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")

    def _send(self, status: int, payload: bytes, content_type: str | None) -> None:
        self.close_connection = True
        self.send_response(status)
        self._cors()
        self.send_header("Connection", "close")
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD" and payload:
            self.wfile.write(payload)
        with self.lock:
            self.events.append(f"{self.command} {self._path()} {status}")

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _auth_or_error(self) -> bool:
        token = self._bearer()
        if token == "overflow":
            self._json(429, {"error": "full"})
            return False
        if token != TOKEN:
            self._json(401, {"error": "unauthorized"})
            return False
        return True

    def do_OPTIONS(self) -> None:
        self._send(204, b"", None)

    def do_GET(self) -> None:
        path = self._path()
        if path == "/v1/health":
            self._json(200, {"version": "test", "ready": True})
            return
        if path == "/page.html":
            page = (
                "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\"><title>ilt</title></head>"
                "<body><nav><img id=\"chrome\" alt=\"шапка\" src=\"/pic.png\" width=\"32\" height=\"32\"></nav>"
                "<img id=\"pic\" alt=\"страница\" src=\"/pic.png\" width=\"220\" height=\"220\"></body></html>"
            )
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/pic.png":
            self._send(200, self.page_png, "image/png")
            return
        if path.startswith("/v1/jobs/"):
            if not self._auth_or_error():
                return
            rest = path[len("/v1/jobs/") :]
            want_result = rest.endswith("/result")
            job_id = urllib.parse.unquote(rest[: -len("/result")] if want_result else rest)
            with self.lock:
                job = self.jobs.get(job_id)
            if not job or "/" in job_id:
                self._json(404, {"error": "not found"})
                return
            if want_result:
                self._send(200, self.result_png, "image/png")
                return
            self._json(200, job)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self._path()
        if path == "/v1/pair":
            raw = self._body()
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                data = {}
            code = str(data.get("code", "")).strip()
            if code != PAIR_CODE:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, {"token": TOKEN})
            return
        if path == "/v1/translate":
            self._body()
            if not self._auth_or_error():
                return
            with self.lock:
                self.seq += 1
                job_id = f"job{self.seq}"
                self.jobs[job_id] = {
                    "id": job_id,
                    "status": "done",
                    "stage": "готово",
                    "position": 0,
                    "error": None,
                }
            self._json(202, {"job_id": job_id})
            return
        self._body()
        self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        path = self._path()
        if not path.startswith("/v1/jobs/"):
            self._json(404, {"error": "not found"})
            return
        if not self._auth_or_error():
            return
        job_id = urllib.parse.unquote(path[len("/v1/jobs/") :])
        with self.lock:
            self.jobs.pop(job_id, None)
        self._send(204, b"", None)


def _png_bytes(size: int, rgb: tuple[int, int, int]) -> bytes:
    spec = importlib.util.spec_from_file_location("build_extension", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.png_bytes(size, rgb, rgb)


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    ApiHandler.jobs = {}
    ApiHandler.events = []
    ApiHandler.lock = threading.Lock()
    ApiHandler.seq = 0
    ApiHandler.page_png = _png_bytes(220, (30, 90, 160))
    ApiHandler.result_png = _png_bytes(32, (200, 48, 48))
    server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    thread = threading.Thread(target=server.serve_forever, name="ilt-api", daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


def _extension_id(context) -> str:
    def pick() -> str:
        for worker in context.service_workers:
            url = worker.url or ""
            if url.startswith("chrome-extension://"):
                return url.split("/")[2]
        return ""

    found = pick()
    if found:
        return found
    context.wait_for_event("serviceworker", timeout=20000)
    found = pick()
    if not found:
        raise AssertionError("service worker расширения не поднялся")
    return found


def _wait_status(page, needle: str) -> None:
    try:
        page.wait_for_function(
            """(needle) => (document.querySelector("#status")?.textContent || "").includes(needle)""",
            arg=needle,
            timeout=15000,
        )
    except Exception as exc:
        status = ""
        try:
            status = page.locator("#status").inner_text(timeout=1000)
        except Exception:
            status = ""
        raise AssertionError(f"ждали «{needle}», на странице «{status}». Журнал: {ApiHandler.events}") from exc


def _state(page) -> dict:
    return page.evaluate(
        """() => ({
          stage: document.querySelector(".ilt-stage")?.textContent || "",
          src: document.querySelector("#pic")?.src || "",
          phase: document.querySelector("#pic")?.dataset?.iltPhase || "",
          original: document.querySelector("#pic")?.dataset?.iltOriginal || "",
          mode: document.querySelector("#pic")?.dataset?.iltMode || ""
        })"""
    )


def test_extension_pairs_and_translates(tmp_path):
    with sync_playwright() as playwright:
        try:
            executable = Path(playwright.chromium.executable_path)
        except Exception as exc:
            pytest.skip(f"Chromium Playwright недоступен: {exc}")
        if not executable.is_file():
            pytest.skip(f"Chromium Playwright не установлен: {executable}")

        subprocess.run([sys.executable, str(SCRIPT)], check=True, cwd=ROOT)
        server, base = _start_server()
        context = None
        logs: list[str] = []
        try:
            ext_dir = DIST.resolve().as_posix()
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(tmp_path / "profile"),
                    headless=False,
                    viewport={"width": 960, "height": 720},
                    ignore_default_args=["--disable-extensions"],
                    args=[
                        f"--disable-extensions-except={ext_dir}",
                        f"--load-extension={ext_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-features=PrivateNetworkAccessSendPreflights,"
                        "PrivateNetworkAccessRespectPreflightResults,"
                        "BlockInsecurePrivateNetworkRequests,LocalNetworkAccessChecks",
                    ],
                )
            except Exception as exc:
                message = str(exc)
                if "Executable doesn't exist" in message or "BrowserType.launch" in message:
                    pytest.skip(message)
                raise

            context.on("page", lambda page: page.on("console", lambda msg: logs.append(msg.text)))
            extension_id = _extension_id(context)
            page = context.pages[0] if context.pages else context.new_page()
            page.on("console", lambda msg: logs.append(msg.text))
            page.goto(f"chrome-extension://{extension_id}/options.html")
            page.locator("#server-url").fill(base)
            page.locator("#pair-code").fill(PAIR_CODE)
            page.locator("#pair").click()
            _wait_status(page, "сопряжено")
            page.locator("#check").click()
            _wait_status(page, "связь есть")

            image = context.new_page()
            image.on("console", lambda msg: logs.append(msg.text))
            image.on("pageerror", lambda err: logs.append(str(err)))
            image.goto(f"{base}/page.html")
            image.wait_for_function(
                """() => {
                  const pic = document.querySelector("#pic");
                  const chrome = document.querySelector("#chrome");
                  return pic && pic.complete && pic.naturalWidth > 180
                    && chrome && chrome.complete && chrome.naturalWidth > 180
                    && document.querySelector(".ilt-btn")
                    && chrome.dataset.iltBound !== "1";
                }""",
                timeout=15000,
            )
            shown = image.evaluate(
                """() => {
                  const pic = document.querySelector("#pic");
                  pic.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
                  const btn = document.querySelector(".ilt-btn");
                  return getComputedStyle(btn).display;
                }"""
            )
            assert shown == "none"
            image.wait_for_function(
                """() => getComputedStyle(document.querySelector(".ilt-btn")).display !== "none" """,
                timeout=4000,
            )
            image.evaluate(
                """() => {
                  const btn = document.querySelector(".ilt-btn");
                  if (!btn) throw new Error("нет кнопки");
                  btn.click();
                }"""
            )
            try:
                image.wait_for_function(
                    """() => {
                      const img = document.querySelector("#pic");
                      return img
                        && img.src.startsWith("blob:")
                        && (img.dataset.iltOriginal || "").includes("pic.png");
                    }""",
                    timeout=20000,
                )
            except Exception as exc:
                raise AssertionError(f"перевод не подменил src: {_state(image)}; журнал {ApiHandler.events}; консоль {logs}") from exc

            image.evaluate("""() => document.querySelector(".ilt-badge").click()""")
            image.wait_for_function(
                """() => {
                  const img = document.querySelector("#pic");
                  return img.dataset.iltMode === "original" && img.src.includes("pic.png");
                }""",
                timeout=5000,
            )
            image.evaluate("""() => document.querySelector(".ilt-badge").click()""")
            image.wait_for_function(
                """() => document.querySelector("#pic").src.startsWith("blob:")""",
                timeout=5000,
            )

            joined = "\n".join(ApiHandler.events)
            assert "POST /v1/pair 200" in joined
            assert "GET /v1/health 200" in joined
            assert "POST /v1/translate 202" in joined
            assert any(line.startswith("GET /v1/jobs/") and line.endswith("/result 200") for line in ApiHandler.events)
        finally:
            if context is not None:
                context.close()
            server.shutdown()
            server.server_close()
