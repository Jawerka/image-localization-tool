# Tasks: 030-runtime-deployment

## Spec & plan

- [x] T001 `spec.md` (US1–US6, FR-001…FR-015), `research.md` (spike + находки), `data-model.md`, `contracts/runtime-api.md`
- [x] T002 `plan.md`

## Code — ядро

- [x] T003 `src/app/runtime.py`: `PackInfo`, манифест (встроенный + URL), `status()`, `download_and_install()`, `remove()`, `activate()`, `torch_ready()/argos_ready()`, фоновый `Manager` с событиями
- [x] T004 `src/app/runtime_manifest.json`: встроенная копия манифеста (win/linux)
- [x] T005 `src/app/hardware.py`: `detect()`, парсеры nvidia-smi/WMI/lspci, кэш
- [x] T006 `src/app/__main__.py`: ранний `stdlib.zip` → `sys.path`, `runtime.startup()`, `ARGOS_PACKAGES_DIR`
- [x] T007 `src/components/lama_inpainter.py`: `resolve_device` без frozen-shortcut (auto→cuda)
- [x] T008 `src/components/translator.py` (+ `llm_translator.py`): сообщение «Нужен компонент Argos» пробрасывается в warnings
- [x] T009 `src/utils/paths.py`: `install_root/models` создаётся при первом обращении

## Code — API и CLI

- [x] T010 `src/app/server.py`: `GET /api/runtime`, `POST /api/runtime/download`, `POST /api/runtime/remove`, поле `runtime` в `_bootstrap`
- [x] T011 `src/app/desktop.py` + `src/app/deploy.py`: `--deploy cpu|cuda|argos|models|all`, идемпотентность, exit codes

## Code — Flutter

- [x] T012 `model/runtime_pack.dart` (+ generic `IltApi.getJson/postJson` для `/api/runtime*`)
- [x] T013 `state/secondary_state.dart`: `runtimePacks`, прогресс `runtime.progress`, методы запуска/удаления; `shell_state.dart` — подписка на `runtime.progress`
- [x] T014 `ui/screens/first_run_screen.dart`: шаг «Компоненты» (рекомендация, размеры, прогресс)
- [x] T015 `ui/screens/settings_screen.dart`: секция «Компоненты» (статус/скачать/удалить, конфликт torch-паков)

## Tests

- [x] T016 `tests/unit/test_runtime.py`: манифест, sha256, распаковка, traversal, remove, status, activate, Manager, sync-fetch манифеста
- [x] T017 `tests/unit/test_hardware.py`: фикстуры nvidia-smi/WMI/lspci (617→cu128, 566→cpu, мусор→cpu)
- [x] T018 `tests/unit/test_lama_device.py`: `resolve_device` auto/явный/frozen-регрессия
- [x] T019 `tests/unit/test_deploy_cli.py`: парсинг и прогон `--deploy` с подменёнными загрузчиками
- [x] T020 `tests/unit/test_server_runtime.py`: endpoint'ы и события
- [x] T021 Flutter: `test/runtime_wizard_test.dart` + `secondary_state_test.dart`

## Verify & Converge

- [x] T022 pytest полный: 448 passed, 7 deselected (slow/ui/llm/argos)
- [x] T023 `flutter analyze` 0 issues + `flutter test` 123 passed
- [ ] T024 CUDA smoke на RTX 5060: cu128-пак, `device=auto` → cuda, LaMa на GPU
- [x] T025 Портативный smoke: portable-zip распакован в чистый каталог, `--deploy cpu` кладёт пак в `runtime/` внутри каталога, `data/` на месте
- [x] T026 Сборка базы без torch + `smoke_dist --expect-no-torch`: sidecar 247 МБ, setup 154 МБ; frozen-сайдкар подхватил внешний CPU-пак (`torch_ready=true`)

## Итог и отклонения

- Пак = `site-packages` целиком (spike: torch тянет `torchgen` и deps вне `torch/`).
- `stdlib.zip` (~3 МБ) добавлен в `_internal` базы: frozen stdlib неполон (spike: `timeit`).
- Пак сжимается сильно лучше оценки: CPU — 61 МБ, Argos — 37 МБ, CUDA — см. 031.
- Прямой запуск `sidecar\...exe --deploy` без `ILT_INSTALL_ROOT` кладёт паки рядом с exe (как и раньше с моделями); Flutter-хост и server-раскладка задают корень корректно.
