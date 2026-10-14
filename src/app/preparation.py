"""Сохранённая очередь подготовки приложения, пауза и продолжение после запуска."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import sys
import importlib.util
import importlib.metadata
from pathlib import Path

from src.app import component_catalog, downloads, runtime
from src.app.events import WorkerEvent
from src.utils.paths import components_root

ACTIVE = ("downloading", "installing", "checking", "planning")


def catalog_hash() -> str:
    resources = Path(component_catalog.__file__).with_name("component_manifest.json").read_bytes()
    manifest = json.dumps(runtime.load_manifest(), sort_keys=True).encode()
    return hashlib.sha256(resources + manifest).hexdigest()


def plan(selection: dict) -> dict:
    """Зафиксировать набор до начала загрузки, без секретов и сетевого resolve."""
    from src.app.hardware import detect

    selected = {"source_lang": str(selection.get("source_lang") or "en"),
                "target_lang": str(selection.get("target_lang") or "ru"),
                "translator_backend": str(selection.get("translator_backend") or "llm"),
                "inpainter_backend": str(selection.get("inpainter_backend") or "lama"),
                "device": str(selection.get("device") or "auto"),
                "models_dir": str(selection.get("models_dir") or "")}
    if selected["translator_backend"] not in ("llm", "argos") or selected["device"] not in ("auto", "cpu", "cuda"):
        raise ValueError("Неизвестный режим подготовки")
    available = runtime.platform_packs()
    recommended = str(detect().get("recommended") or "torch-cpu")
    torch_id = "torch-cpu" if selected["device"] == "cpu" else recommended
    if torch_id not in {p.id for p in available}:
        torch_id = "torch-cpu"
    ids = ["detector", "rapidocr", "font", "font-pack"]
    runtime_ids = []
    if selected["inpainter_backend"] != "opencv":
        ids.append("lama")
        runtime_ids.append(torch_id)
    language_id = f"language-{selected['source_lang']}-{selected['target_lang']}"
    resources = component_catalog.load()
    warnings = []
    if selected["source_lang"] != selected["target_lang"]:
        if language_id in {c.id for c in resources}:
            runtime_ids.append("argos")
            ids.append(language_id)
        elif selected["translator_backend"] == "argos":
            raise ValueError("Это направление оффлайн-перевода пока не поддерживается. Выберите сервер LLM.")
        else:
            warnings.append("Для выбранных языков доступен перевод через LLM; оффлайн-фолбэк пока не подготовлен.")
    items = []
    for pack_id in runtime_ids:
        if pack_id not in {p.id for p in available} and not getattr(sys, "frozen", False):
            module = "torch" if pack_id.startswith("torch-") else "argostranslate"
            if importlib.util.find_spec(module) is None:
                raise ValueError("Для запуска из исходников установите зависимости requirements.txt")
            version = importlib.metadata.version(module)
            check = "torch-cuda" if pack_id.startswith("torch-cu") else "torch" if module == "torch" else "argos"
            revision = hashlib.sha256(f"{module}:{version}:{runtime.python_tag()}:{check}".encode()).hexdigest()
            builtin_path = components_root() / ".builtin" / f"{revision}.json"
            from src.app.component_check import validation_identity
            try:
                checked = json.loads(builtin_path.read_text()).get("checker") == validation_identity()
            except (OSError, ValueError):
                checked = False
            items.append({"id": module, "title": "Компонент из окружения разработки", "type": "builtin",
                "revision": revision, "check": check, "size_bytes": 0, "unpacked_bytes": 0,
                "download_bytes": 0, "install_bytes": 0, "ready": checked})
            continue
        pack = runtime.pack_by_id(pack_id)
        items.append({"id": pack.id, "title": pack.title, "type": "runtime", "revision": pack.revision,
                      "size_bytes": pack.effective_size, "unpacked_bytes": pack.unpacked_bytes or pack.effective_size * 4,
                      "ready": runtime.ready(pack) and (pack.kind != "torch" or runtime.selected_torch_id() == pack.id)})
    for component_id in ids:
        component = next(c for c in resources if c.id == component_id)
        items.append({"id": component.id, "title": component.title, "type": "resource", "revision": component.revision,
                      "size_bytes": component.size_bytes, "unpacked_bytes": component.size_bytes * (4 if component.kind == "language" else 1),
                      "ready": component_catalog.ready(component)})
    # Runtime идёт прежде моделей, чтобы чистые probes видели нужные библиотеки.
    def missing(files):
        count = 0
        cache = downloads.cache_root()
        for item in files:
            if downloads.valid(cache / f"{item.sha256}.blob", item):
                continue
            partial = cache / f"{item.sha256}.part"
            offset = min(item.size_bytes, partial.stat().st_size) if partial.is_file() else 0
            count += item.size_bytes - offset
        return count

    for item in items:
        if item["type"] == "builtin":
            continue
        files = (runtime.pack_by_id(item["id"]).files if item["type"] == "runtime"
                 else component_catalog.by_id(item["id"]).files)
        artifacts = [downloads.Artifact(f.name, (f.url,), f.sha256, f.size_bytes)
                     if isinstance(f, runtime.WheelFile) else f for f in files]
        existing = (runtime.matches(runtime.pack_by_id(item["id"])) if item["type"] == "runtime"
                    else component_catalog.ready(component_catalog.by_id(item["id"]), ignore_checker=True))
        item["download_bytes"] = 0 if existing else missing(artifacts)
        item["install_bytes"] = 0 if existing else item["unpacked_bytes"]
    total = sum(item["download_bytes"] for item in items)
    return {"schema": 1, "selection": selected, "catalog_sha": catalog_hash(), "items": items,
            "total": total, "done": 0, "index": 0, "current": "", "state": "ready" if all(i["ready"] for i in items) else "idle",
            "torch": torch_id, "warnings": warnings, "error": "", "error_kind": "",
            "required_space": total + sum(i["install_bytes"] for i in items)}


class Manager:
    """Один persisted coordinator на сервер; OS-lock защищает также CLI и второй процесс."""

    def __init__(self, fanout=None, path: Path | None = None, on_ready=None, can_install=None):
        from src.app.paths import data_root

        self.path = path or data_root() / "preparation.json"
        self.fanout = fanout
        self.on_ready = on_ready
        self.can_install = can_install
        self._lock = threading.RLock()
        self._pause = threading.Event()
        self._thread = None
        self._last_saved = 0.0
        self._state = {"state": "idle", "items": [], "total": 0, "done": 0, "error": "", "error_kind": ""}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if saved.get("schema") == 1 and isinstance(saved.get("items"), list):
                self._state = saved
                if saved["state"] in ACTIVE:
                    self._state["state"] = "paused"
                    self._save()
        except (OSError, ValueError, KeyError):
            pass

    def current(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def busy(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, selection: dict | None = None):
        with self._lock:
            if self.busy():
                raise downloads.BusyError("Подготовка уже идёт")
            if self.can_install is not None and not self.can_install():
                raise downloads.BusyError("Дождитесь завершения обработки страниц перед подготовкой компонентов")
            if selection is not None or not self._state.get("selection"):
                self._state = plan(selection or {})
            elif self._state.get("catalog_sha") != catalog_hash():
                raise ValueError("Каталог изменился. Создайте новый план подготовки; скачанные файлы сохранятся.")
            self._pause.clear()
            self._state.update(state="planning", error="", error_kind="")
            self._save()
            self._thread = threading.Thread(target=self._run, name="ilt-preparation", daemon=True)
            self._thread.start()
            return self.current()

    def pause(self):
        self._pause.set()
        if not self.busy():
            self._update(state="paused")
        return self.current()

    def resume(self):
        return self.start()

    def _save(self):
        self._state["updated_at"] = time.time()
        downloads.atomic_json(self.path, self._state)
        self._last_saved = time.monotonic()

    def _update(self, **values):
        with self._lock:
            previous = self._state.get("state")
            self._state.update(values)
            if previous != self._state.get("state") or time.monotonic() - self._last_saved >= 0.5:
                self._save()
            snapshot = self.current()
        if self.fanout:
            self.fanout(WorkerEvent("preparation.progress", snapshot))

    def _run(self):
        try:
            with downloads.installer_lock():
                state = self.current()
                downloads.ensure_space(components_root(), state["required_space"])
                done = 0
                for index, item in enumerate(state["items"]):
                    downloads.check_pause(self._pause)
                    self._update(index=index, current=item["title"])
                    def progress(n, total, stage, message):
                        credit = item["size_bytes"] - item.get("download_bytes", item["size_bytes"])
                        self._update(done=done + max(0, n - credit), state="checking" if stage == "installed" else stage)

                    if item["type"] == "builtin":
                        from src.app.component_check import probe, validation_identity

                        self._update(state="checking")
                        probe({"kind": item["check"]})
                        downloads.atomic_json(components_root() / ".builtin" / f"{item['revision']}.json",
                                              {"checker": validation_identity()})
                    elif item["type"] == "runtime":
                        pack = runtime.pack_by_id(item["id"])
                        if pack.revision != item["revision"]:
                            raise ValueError("Состав компонента изменился")
                        runtime.download_and_install(pack, progress, pause=self._pause)
                    else:
                        component = component_catalog.by_id(item["id"])
                        if component.revision != item["revision"]:
                            raise ValueError("Состав ресурса изменился")
                        component_catalog.install(component, progress,
                                                  self._pause, state["selection"]["models_dir"])
                    done += item.get("download_bytes", item["size_bytes"])
                    with self._lock:
                        self._state["items"][index]["ready"] = True
                    self._update(done=done)
                if self.on_ready:
                    self.on_ready()
                from src.config import Config

                downloads.clear_cache(max_bytes=Config().download_cache_limit_mb * 1024 * 1024)
                self._update(state="ready", current="", done=state["total"], error="", error_kind="")
                with self._lock:
                    self._save()
        except downloads.Paused:
            self._update(state="paused", error="", error_kind="")
        except Exception as exc:
            kind = ("disk" if isinstance(exc, downloads.DiskError) else
                    "permission" if isinstance(exc, PermissionError) else
                    "busy" if isinstance(exc, downloads.BusyError) else
                    "integrity" if isinstance(exc, downloads.IntegrityError) else
                    "network" if isinstance(exc, downloads.DownloadError) else "compatibility")
            self._update(state="error", error=str(exc), error_kind=kind)
            with self._lock:
                self._save()
