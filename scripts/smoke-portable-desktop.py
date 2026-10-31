"""Запустить Flutter из чистой portable и проверить реальный sidecar через его API."""

import argparse
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    args = parser.parse_args()
    app = Path(args.app).resolve()
    workspace = Path(__file__).resolve().parents[1]
    if not app.is_relative_to(workspace / "build"):
        raise ValueError("Desktop smoke разрешён только для отдельной распаковки внутри build")
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        assert (app / "desktop" / name).is_file(), f"Нет локальной библиотеки {name}"
    tool = app / "tools" / "7zip" / "7z.exe"
    assert tool.is_file() and (tool.parent / "License.txt").is_file()
    check_tool = subprocess.run([str(tool), "i"], capture_output=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert check_tool.returncode == 0
    env = {key: value for key, value in os.environ.items() if not key.startswith("ILT_")
           and key not in {"ARGOS_PACKAGES_DIR", "ARGOS_TRANSLATE_PACKAGE_DIR", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"}}
    env.update(ILT_INSTALL_ROOT=str(app), ILT_COMPONENT_ROOT=str(app), ILT_DATA_DIR=str(app / "data"))
    handshake = app / "data" / "api.json"
    handshake.unlink(missing_ok=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    host = subprocess.Popen([str(app / "desktop" / "ImageLocalizationTool.exe")], cwd=app, env=env,
                            startupinfo=startup)
    session = requests.Session()
    session.trust_env = False
    try:
        deadline = time.monotonic() + 40
        while not handshake.exists():
            if host.poll() is not None:
                raise RuntimeError(f"Flutter завершился: {host.returncode}")
            if time.monotonic() > deadline:
                raise TimeoutError("Flutter не получил handshake sidecar")
            time.sleep(0.2)
        ready = json.loads(handshake.read_text(encoding="utf-8-sig"))
        base = f"http://127.0.0.1:{ready['port']}"

        def call(method, path, body=None):
            result = session.request(method, base + path, json=body, timeout=60)
            if not result.ok:
                raise RuntimeError(f"{path}: {result.status_code}: {result.text[:500]}")
            return result.json()

        def wait_job(job_id):
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                current = call("GET", f"/api/jobs/status?job_id={job_id}")
                if current["status"] == "done":
                    return current
                if current["status"] in {"error", "cancelled"}:
                    raise RuntimeError(str(current))
                time.sleep(0.5)
            raise TimeoutError(job_id)

        call("POST", "/api/session", {"token": ready["token"]})
        bootstrap = call("GET", "/api/bootstrap")
        assert bootstrap["settings"]["first_run_complete"] is True
        assert bootstrap["settings"]["device"] == "cpu"
        for source, target in (("en", "ru"), ("ru", "en")):
            plan = call("POST", "/api/preparation/plan", {"source_lang": source, "target_lang": target,
                "translator_backend": "argos", "device": "cpu"})
            assert plan["state"] == "ready" and plan["total"] == 0
        source = app / "data" / "offline-source.png"
        assert source.is_file(), "Сначала выполните smoke-components --prepared"
        imported = call("POST", "/api/drop", {"paths": [str(source)]})
        assert imported["pages"]
        translated = wait_job(call("POST", "/api/jobs/translate", {"scope": "all"})["job_id"])
        export = app / "data" / "desktop-smoke-export"
        export.mkdir(exist_ok=True)
        call("POST", "/api/dialog/directory", {"path": str(export)})
        result = wait_job(call("POST", "/api/jobs/export", {"archive": "zip"})["job_id"])
        path = export / "export.zip"
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path) as archive:
            assert any(name.lower().endswith(".png") for name in archive.namelist())
        assert host.poll() is None
        (app / "data" / "desktop-smoke-report.json").write_text(json.dumps({"ok": True,
            "host": "Flutter", "profile": "cpu-full", "translate": translated["status"],
            "export": result["status"]}), encoding="utf-8")
        print("Flutter + frozen sidecar: prepared profile, real translation and ZIP export OK", flush=True)
    finally:
        session.close()
        if host.poll() is None:
            host.terminate()
            host.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
