# Implementation Plan: Runtime Deployment

**Branch**: `030-runtime-deployment` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/030-runtime-deployment/spec.md`

## Summary

База без torch: frozen-сайдкар активирует внешние паки из `<install_root>/runtime/<id>/site-packages`,
добавляя пути в `sys.path` и DLL-каталоги; `stdlib.zip` в `_internal` закрывает неполноту frozen-stdlib
(spike, [research.md](./research.md)). Новые модули `src/app/runtime.py` (манифест, статус, загрузка,
распаковка, удаление, активация) и `src/app/hardware.py` (детект NVIDIA/драйвера). `resolve_device`
больше не форсирует cpu во frozen. API: `/api/runtime*` + SSE `runtime.progress`. CLI `--deploy`.
Flutter: шаг «Компоненты» в мастере и секция в настройках.

## Technical Context

**Language/Version**: Python 3.10 (релиз, PyInstaller), Dart 3.13.5 / Flutter stable 3.47.7
**Primary Dependencies**: py7zr (уже в базе), stdlib (`urllib`, `hashlib`, `subprocess`, `shutil`);
новых зависимостей нет
**Storage**: `<install_root>/runtime/<id>/` (packs), `data/argos-packages` (языковые модели Argos)
**Testing**: pytest (manifest, sha, распаковка, hardware-фикстуры, resolve_device, endpoints, CLI),
`flutter test` + `flutter analyze`
**Target Platform**: Windows x64 (основной), Linux x64 (сервер, CI)
**Constraints**: минимальный diff; русские комментарии; не ломать контракт `/api/*`; база без torch
**Scale/Scope**: 2 новых модуля Python, правки ~6 Python-файлов, ~6 Flutter-файлов, тесты

## Constitution Check

- Pipeline v2 не тронут — PASS (меняется только выбор устройства и ленивый импорт torch)
- Минимальный diff — PASS (новые движки — новые файлы; настройки в существующих классах)
- Комментарии на русском — PASS
- Локальные данные не коммитить — PASS (паки/модели — вне git)
- Совместимость — PASS (CLI, окно, LAN, extension не удаляются; `/api/*` только дополняется)
- Заявленное качество — PASS (не меняется)

## Изменения

### 1. `src/app/runtime.py` (новый)

- `PackInfo`/`RuntimeStatus` (dataclasses): id, kind, platform, version, url, sha256, size_bytes,
  state, installed_path, installed_bytes, error, recommended.
- `manifest()`: встроенная копия (`src/app/runtime_manifest.json`) + fetch по
  `ILT_RUNTIME_MANIFEST_URL` (по умолчанию — URL ассета текущего релиза по `__version__`), кэш на процесс.
- `status()`: читает `runtime/`, маркер `pack.json`, сверяет версию с манифестом.
- `download_and_install(id, progress, cancel=None)`: `.part` → sha256 → py7zr extract в `<id>.tmp`
  (проверка path traversal) → `pack.json` → atomic rename; при ошибке — очистка.
- `remove(id)`.
- `activate()`: вызывается из `src/app/__main__.py` до импорта пайплайна; порядок torch-паков:
  `torch-cu128` → `torch-cpu` → `argos`; добавляет `site-packages` в `sys.path`, `torch/lib` в DLL-пути,
  `stdlib.zip` из `_MEIPASS`/репозитория в `sys.path` (в конце). Возвращает активированные id.
- `torch_ready()` / `argos_ready()`: проверка без импорта (наличие каталогов) + ленивая проверка import.
- `Manager` (для сервера): один поток загрузки, SSE-события `runtime.progress`, статус «идёт».

### 2. `src/app/hardware.py` (новый)

- `detect()` c кэшем: `nvidia-smi --query-gpu=name,driver_version --format=csv,noheader` (timeout 5);
  парсинг «NVIDIA GeForce RTX 5060 Laptop GPU, 617.14»; `vendor=nvidia`, `driver=617`,
  `recommended=torch-cu128` при `driver >= 570`, иначе `torch-cpu` + reason; нет nvidia-smi → не NVIDIA.
- AMD/Intel: Windows — `powershell Get-CimInstance Win32_VideoController` (best-effort, timeout 5);
  Linux — `lspci` (best-effort); всегда `recommended=torch-cpu`.
- Функции чистые: парсеры отдельно от запуска процессов (тестируемость фикстурами).

### 3. Устройство и активация

- `src/components/lama_inpainter.py::resolve_device`: убрать `sys.frozen → cpu`; `auto` → `cuda`,
  если `torch.cuda.is_available()`; fallback `cuda → cpu` сохраняется.
- `src/app/__main__.py`: ранний вызов `runtime.activate()` (frozen и dev) до `prepare_logging`? Нет —
  после `install_null_stdio`, но до `desktop.launch`/`--deploy`; `stdlib.zip` — первым делом.
  Также `os.environ.setdefault("ARGOS_PACKAGES_DIR", str(data_root() / "argos-packages"))`.
- `src/utils/paths.py::models_dir`: создавать `install_root/models` при первом обращении (frozen),
  чтобы портативная папка появилась до скачивания.
- `src/components/translator.py`: при ImportError argostranslate — текст ошибки «требуется пак Argos
  (Компоненты → Argos) или LLM-сервер», доступный UI.

### 4. API (`src/app/server.py`)

- `GET /api/runtime` → `{platform, python, packs: [...], hardware: {...}, torch_ready, argos_ready,
  device, device_effective}`.
- `POST /api/runtime/download` `{id}` → 202 `{ok: true}`; поток `runtime.Manager` шлёт
  `runtime.progress` через `state.fanout` (как `model.progress`).
- `POST /api/runtime/remove` `{id}` → `{ok: true}`.
- `_bootstrap`: поле `runtime: {installed: [...], recommended, torch_ready, argos_ready}`.
- `AppState`: ленивое создание `runtime.Manager` (не в `__init__`, чтобы не сканировать диск у тестов
  без runtime).

### 5. CLI `--deploy`

- `src/app/desktop.py`: `--deploy` c `nargs="+"`, choices `cpu|cuda|argos|models|all`; при наличии —
  без окна/сервера, выполняет и завершает процесс кодом 0/1; печать прогресса в stdout.
- `models` — переиспользует `model_manager.download` (+ font_pack), `cpu/cuda/argos` — `runtime`;
  `all` = `models` + `argos` + torch по `hardware.detect()["recommended"]`.

### 6. Flutter

- `apps/desktop/lib/src/model/runtime_pack.dart` (новый): модель пака и статуса.
- `apps/desktop/lib/src/state/secondary_state.dart`: список `runtimePacks`, прогресс из
  `runtime.progress`, `startRuntimeDownload(id)`, `removeRuntimePack(id)`, `refreshRuntime()`.
- `apps/desktop/lib/src/ui/screens/first_run_screen.dart`: шаг «Компоненты» между «Моделями»
  и «Сервер LLM»; рекомендация, размеры, прогресс, текст «Можно продолжить позже».
- `apps/desktop/lib/src/ui/screens/settings_screen.dart`: секция «Компоненты» (статус, скачать,
  удалить, конфликт torch-паков).
- `apps/desktop/lib/src/api/ilt_api.dart`: `getRuntime()`, `downloadRuntime(id)`, `removeRuntime(id)`.

### 7. Релизная база (детали — спека 031)

- `requirements-release.txt` без torch/Argos/dev; excludes в `ImageLocalizationTool.spec`;
- `stdlib.zip` в `_internal` (spec datas) — из `scripts/build-windows.ps1` (генерация);
- `scripts/smoke_dist.py`: base без torch — не требовать `torch/lib`; проверять `stdlib.zip`.

## Тесты

- `tests/unit/test_runtime.py`: манифест (встроенный/URL), sha256 (good/bad), распаковка `.7z`
  (собираем архив py7zr), path traversal, `remove`, `status` c маркером, порядок `activate`.
- `tests/unit/test_hardware.py`: парсеры nvidia-smi (617 → cu128, 566 → cpu, мусор → cpu),
  vendor AMD/Intel (фикстуры без реальных процессов).
- `tests/unit/test_lama_device.py`: `resolve_device` auto/явный; monkeypatch torch.
- `tests/unit/test_deploy_cli.py`: `--deploy models` c monkeypatched downloader; идемпотентность.
- `tests/unit/test_server_runtime.py` (по образцу тестов server): `/api/runtime`, download/remove,
  события SSE через шину.
- Flutter: `test/runtime_wizard_test.dart` (шаг мастера, кнопки/прогресс), обновление
  `secondary_state` тестов.

## Project Structure

```text
specs/030-runtime-deployment/{spec,plan,tasks,research,data-model}.md
specs/030-runtime-deployment/contracts/runtime-api.md

src/app/{runtime.py,hardware.py,runtime_manifest.json}
src/app/{__main__.py,server.py,desktop.py}
src/components/{lama_inpainter.py,translator.py}
src/utils/paths.py

apps/desktop/lib/src/{model/runtime_pack.dart,state/secondary_state.dart,
  api/ilt_api.dart,ui/screens/{first_run_screen.dart,settings_screen.dart}}
apps/desktop/test/runtime_wizard_test.dart

tests/unit/{test_runtime.py,test_hardware.py,test_lama_device.py,test_deploy_cli.py,test_server_runtime.py}
```

## Converge

- pytest полный; `flutter analyze` + `flutter test`.
- Сборка базы (`build-windows.ps1 -SkipModels`): проверка размера и `smoke_dist`.
- CUDA smoke на RTX 5060: установка cu128-пака (из локального файла), `device=auto`, LaMa на GPU.
- Портативный smoke: распаковка portable-zip, скачивание модели/пака внутрь каталога.

## Complexity Tracking

| Item | Why |
|------|-----|
| `stdlib.zip` в базе | frozen-интерпретатор без него не тянет stdlib-модули, нужные torch (spike) |
| Пак = site-packages целиком | torch тянет `torchgen` и deps, лежащие вне `torch/` (spike) |
| Своя шина `runtime.progress` | 1.2 ГБ и минуты — нельзя держать HTTP-запрос синхронным, как models |
| `activate()` в `__main__` | torch импортируется лениво из пайплайна; путь обязан быть в `sys.path` до этого |
