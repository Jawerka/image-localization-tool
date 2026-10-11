# Tasks: 026-cutover

## Spec & plan

- [x] T001 `spec.md` (US1–US5, FR-001…FR-015) + `plan.md` (раскладка `desktop/` + `sidecar/`, резолвинг путей, фокус, упаковка)

## Host

- [x] T002 `sidecar_controller.dart`: резолвинг команды сайдкара — `ILT_SIDECAR_EXE` → `{installRoot}/sidecar/ImageLocalizationTool.exe` → dev `ILT_PYTHON`/`python -m src.app --api`; spawn с env `ILT_INSTALL_ROOT` и cwd=install root во frozen-раскладке
- [x] T003 `data_root.dart`: пользовательский data — `ILT_DATA_DIR` → `repoRoot/data` → `{installRoot}/data` → `%LOCALAPPDATA%`; `desktop/data` (ассеты Flutter) больше не кандидат
- [x] T004 `window_focus.dart` (новый, `win32` 6.4.0 + `ffi`): `allowForegroundTo(pid)` + `focusMainWindow` (FindWindow по заголовку + pid, SW_RESTORE + SetForegroundWindow, no-op вне Windows); `main.dart`: второй запуск всегда фокусирует, затем форвардит непустые пути; `pubspec.yaml` + `win32`, `ffi`
- [x] T005 `windows/CMakeLists.txt` BINARY_NAME → `ImageLocalizationTool`; `Runner.rc` — «Image Localization Tool»; после переименования потребовался `flutter clean` (старый CMake-таргет в кеше)

## Server

- [x] T006 `src/utils/paths.py`: `install_root()` учитывает `ILT_INSTALL_ROOT` (хост задаёт корень установки для сайдкара); docstring

## Packaging

- [x] T007 `ImageLocalizationTool.spec`: COLLECT name → `ilt_sidecar` (exe остаётся `ImageLocalizationTool.exe`); `_StagedCollect` переведён на `sidecar_name`
- [x] T008 `build-windows.ps1`: `Resolve-Flutter` (PATH → `%LOCALAPPDATA%\flutter\bin\flutter.bat`), `-SkipFlutter`, `flutter build windows --release --build-name/--build-number` из `__version__`, сборка раскладки (`desktop/`, `sidecar/`, `web/`, `fonts/`, опц. `models/`), удаление устаревших корневых exe/`_internal`, smoke
- [x] T009 `smoke_dist.py`: проверка новой раскладки (хост, рантайм Flutter, сайдкар + `_internal` + torch под сайдкаром, `web/`, `fonts/`, без mockups)
- [x] T010 `installer/ImageLocalizationTool.iss`: ярлыки/Run → `{app}\desktop\...`; `[InstallDelete]` старого корневого exe и `_internal`; блок WebView2 удалён
- [x] T011 `deploy-windows.ps1`: проверки целостности новой раскладки (хост, сайдкар, `web/`)
- [x] T012 Документация: `apps/desktop/README.md` (пин ≥ 3.47.7, раскладка, резолвинг), `docs/APP.md` + `README.md` (поставляемое приложение — Flutter-хост, `python -m src.app` — dev-вход); CI-комментарий уже был актуален

## SDK

- [x] T013 Flutter обновлён 3.44.0 → **3.47.7** stable (Dart 3.13.5), `flutter upgrade`; несовместимостей кода нет; `environment.sdk: ^3.12.0` — пол совместим

## Tests & CI

- [x] T014 pytest: `test_packaging.py` — новая раскладка smoke, отсутствие WebView2 в установщике, COLLECT `ilt_sidecar`, `_fake_dist`; `test_paths.py` — `ILT_INSTALL_ROOT`; 20 passed по файлам
- [x] T015 flutter: замороженный сайдкар и `ILT_INSTALL_ROOT`, data-корень без `desktop/data`, `frozenSidecarPath`; `flutter analyze` clean + **106 passed** (было 103)
- [x] T016 pytest полный: **385 passed**, 1 pre-existing (`test_text_style.py::test_rotated_layer_stays_on_block_center`, падает и на чистом HEAD — не регрессия)

## Converge

- [x] T017 Сборка: `build-windows.ps1 -SkipModels` → dist `desktop/ + sidecar/ + web/ + fonts/` проходит `smoke_dist.py`; Inno собрал `dist\ImageLocalizationTool-1.0.0-windows-x64-setup.exe` (~1.7 ГБ)
- [x] T018 Ручная приёмка на dist (изолированный `ILT_DATA_DIR`, `test-img`):
  - старт: окно «Image Localization Tool» + `api.json` + `GET /api/bootstrap` (version 1.0.0) за **1,5 с** (SC-002 ≤ 8 с)
  - второй запуск с `test-img\test-1.jpg`: exit 0 за 1,1 с, окно первого уходит на передний план (`GetForegroundWindow` = hwnd первого), страница импортирована (`project.name=Проект`, pages=1) — SC-004
  - закрытие окна (WM_CLOSE): хост закрылся, сайдкар завершён за **0,4 с**, `api.json` удалён, orphan-процессов нет — SC-001/FR-003
  - жёсткое убийство хоста (без закрытия): сайдкар умирает по `--parent-pid` (проверено при отладке скрипта)
  - `logs/app.log` создаётся; диалог выхода/мастер не мешали
- [x] T019 `deploy-windows.ps1` зеркалит `D:\Documents\apps\ImageLocalizationTool`: `desktop/`, `sidecar/`, `web/`, `fonts/`, `models/` сохранены; проверки целостности прошли
- [x] T020 Итог/отклонения — записаны ниже

## Итог и отклонения

- **Полный маршрут open → translate → edit → export на dist не гонялся**: перевод требует LLM/моделей (в 024 smoke он проверен на исходниках). На dist проверены упаковка, жизненный цикл, форвард/фокус и HTTP-цикл; остаток — ручной прогон пользователем на своей машине с LLM.
- 023 T016 (профиль штрихов маски) остаётся опциональным, не блокирует cutover.
- Inno предупреждает: идентификатор `x64` устарел в пользу `x64compatible`; установка работает, смена — отдельным мелким изменением при следующем релизе.
- Фокус реализован через `FindWindow` по заголовку с проверкой pid (без EnumWindows); заголовок задаётся `windows/runner/main.cpp` и стабилен.
- `win32`/`ffi` — единственное расширение зависимостей (план и FR-007 это допускают); `ffi` добавлен явно, т.к. импортируется напрямую.
- Иконка осталась стандартной Flutter (кастомной .ico в репозитории нет) — как зафиксировано в spec.
