"""Сетевые сбои загрузчика воспроизводятся локально, без внешних CDN."""

import hashlib
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.app import downloads


@contextmanager
def server(body, mode="range"):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.headers.get("Range"))
            if mode == "retry" and len(calls) == 1:
                self.send_response(503)
                self.end_headers()
                return
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            if mode == "ignore":
                offset = 0
            if mode == "416" and offset:
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(len(body) - offset))
            if offset:
                start = offset + (1 if mode == "bad_range" else 0)
                self.send_header("Content-Range", f"bytes {start}-{len(body)-1}/{len(body)}")
            self.end_headers()
            if mode == "cut" and len(calls) == 1:
                self.wfile.write(body[:downloads.CHUNK])
                self.wfile.flush()
                self.close_connection = True
                return
            self.wfile.write(body[offset:])

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/file", calls
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def artifact(url, body):
    return downloads.Artifact("test.bin", (url,), hashlib.sha256(body).hexdigest(), len(body))


@pytest.mark.parametrize("mode", ["range", "ignore", "416"])
def test_resume_handles_range_or_restarts_safely(tmp_path, mode):
    body = b"test contents" * 1000
    with server(body, mode) as (url, calls):
        item = artifact(url, body)
        (tmp_path / f"{item.sha256}.part").write_bytes(body[:123])
        result = downloads.fetch(item, tmp_path, retries=1)
        assert result.read_bytes() == body
        assert calls[0] == "bytes=123-"
        downloads.fetch(item, tmp_path)
        assert len(calls) == (2 if mode == "416" else 1)


def test_retry_temporary_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "wait_retry", lambda *args: None)
    with server(b"hello", "retry") as (url, calls):
        assert downloads.fetch(artifact(url, b"hello"), tmp_path, retries=1).read_bytes() == b"hello"
        assert len(calls) == 2


def test_wrong_content_range_never_appends(tmp_path):
    with server(b"hello world", "bad_range") as (url, calls):
        item = artifact(url, b"hello world")
        (tmp_path / f"{item.sha256}.part").write_bytes(b"hello")
        with pytest.raises(downloads.IntegrityError):
            downloads.fetch(item, tmp_path, retries=0)
        assert not (tmp_path / f"{item.sha256}.blob").exists()


def test_corrupt_payload_is_removed(tmp_path):
    with server(b"wrong") as (url, _):
        item = artifact(url, b"right")
        with pytest.raises(downloads.IntegrityError, match="sha256"):
            downloads.fetch(item, tmp_path, retries=0)
        assert not (tmp_path / f"{item.sha256}.part").exists()


def test_checked_cache_repaired_after_corruption(tmp_path):
    with server(b"hello") as (url, calls):
        item = artifact(url, b"hello")
        downloads.fetch(item, tmp_path).write_bytes(b"wrong")
        assert downloads.fetch(item, tmp_path).read_bytes() == b"hello"
        assert len(calls) == 2


def test_mirror_has_same_hash(tmp_path):
    with server(b"wrong") as (bad, _), server(b"right") as (good, _):
        item = downloads.Artifact("test.bin", (bad, good), hashlib.sha256(b"right").hexdigest(), 5)
        assert downloads.fetch(item, tmp_path, retries=0).read_bytes() == b"right"


def test_pause_keeps_partial_for_resume(tmp_path):
    body = b"x" * (downloads.CHUNK * 3)
    paused = threading.Event()
    with server(body) as (url, calls):
        item = artifact(url, body)
        with pytest.raises(downloads.Paused):
            downloads.fetch(item, tmp_path, progress=lambda done, total: paused.set() if done else None,
                            pause=paused)
        assert (tmp_path / f"{item.sha256}.part").stat().st_size == downloads.CHUNK
        assert downloads.fetch(item, tmp_path).read_bytes() == body
        assert calls[-1] == f"bytes={downloads.CHUNK}-"


def test_artifact_rejects_unsafe_names():
    with pytest.raises(ValueError):
        downloads.Artifact("../outside", ("file:///x",), "a" * 64, 1)


def test_low_disk_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads.shutil, "disk_usage", lambda root: type("D", (), {"free": 0})())
    with pytest.raises(downloads.DiskError):
        downloads.fetch(downloads.Artifact("x", ("https://invalid.local",), "a" * 64, 1), tmp_path)


def test_broken_connection_continues_saved_bytes(tmp_path, monkeypatch):
    body = b"x" * (downloads.CHUNK * 3)
    monkeypatch.setattr(downloads, "wait_retry", lambda *args: None)
    with server(body, "cut") as (url, calls):
        assert downloads.fetch(artifact(url, body), tmp_path, retries=1).read_bytes() == body
        assert calls == [None, f"bytes={downloads.CHUNK}-"]


def test_process_lock_survives_nested_entry_and_releases(tmp_path):
    import subprocess
    import sys

    lock = tmp_path / "process.lock"
    code = "from pathlib import Path; from src.app.downloads import file_lock; " \
           "\nwith file_lock(Path(__import__('sys').argv[1])): print('locked')"
    with downloads.file_lock(lock):
        with downloads.file_lock(lock):
            result = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True)
            assert result.returncode != 0
            assert b"BusyError" in result.stderr
    assert subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True).returncode == 0
