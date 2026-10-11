# Tasks: 025-secondary-screens

## Spec & plan

- [x] T001 `spec.md` + `plan.md` (split: style/sfx/отчёт → 024; серверные gap-fix — FR-015)

## Server (gap-fixes)

- [x] T002 `run_api`: LAN стартует при `settings.remote_enabled` (зеркало оконного режима); `_dialog_directory` принимает явный `path`; HTTP-запросы теперь видны в общем `app.log`
- [x] T003 pytest: явный path ставит export_dir и доходит до задания; `run_api` без `--remote` уважает настройку (stub RemoteServer); 44 passed (desktop+server) + 10 (settings)

## State

- [x] T004 `workspace_state.dart`: `settings` (+геттеры темы/масштаба/языков), `updateSettings(patch)` (PUT, only changed), `previewSettings`/`clearPreview`, `firstRunComplete`, `completeFirstRun`
- [x] T005 `secondary_state.dart`: модели (`status`/`download`/прогресс из `model.progress`), удалёнка (`status`/`pair`/`revoke`), глоссарий (`load`/`save`), экспорт-опции, `applyJobFinished` (+открытие папки), ошибки в `errorText`
- [x] T006 `shell_state.dart`: оверлеи (`OverlayKind`), заявка на выход (`confirmExit`/`resolveExit`/`waitForBatchAndExit`), `workerFailure` из событий, `restartSidecar`, `hasApiKey`, `modelsDir`/`logPath`/`dataDir`

## UI

- [x] T007 `settings_screen.dart`: 9 разделов, draft+live preview (тема/масштаб), ОК/Применить/Отмена/Сброс, LLM-проверка и выбор модели, секрет, модели с прогрессом, «О программе», сеть с «Перезапустить API»
- [x] T008 `export_dialog.dart`: области/формат/качество/конфликт, папка через `file_selector` → `/api/dialog/directory {path}`, `/api/jobs/export`, сводка, «Открыть папку»
- [x] T009 `glossary_screen.dart`: таблица, поиск, инлайн-правка, добавить/удалить, PUT, счётчик
- [x] T010 `first_run_screen.dart`: мастер 4 шага, скачивание моделей с прогрессом, «Пропустить всё», запись `first_run_complete`
- [x] T011 `remote_screen.dart`: статус, вкл/выкл+bind/port (применяется после рестарта), код сопряжения, устройства с отзывом, предупреждение, «Что видит устройство»
- [x] T012 диалоги: `hotkeys_dialog` (поиск+таблица), `exit_dialog` (Отмена/Выйти/Дождаться), `worker_dialog` (Повторить ошибки/Открыть лог)
- [x] T013 оболочка: хоткеи F1/Ctrl+,/Ctrl+E/Esc, пункты меню «Файл» (Глоссарий, Настройки, Горячие клавиши, Экспорт), шестерёнка+глобус, оверлей-слой в `app.dart` (Material), `platform.dart`
- [x] T014 first-run авто-показ (один раз), закрытие по завершении/пропуске; выход при прогоне через `AppLifecycleListener` → диалог

## Tests & CI

- [x] T015 `secondary_state_test.dart`: модели/прогресс, удалёнка, глоссарий round-trip, экспорт (папка+задание+итог+открытие), ошибки
- [x] T016 `screens_test.dart`: настройки (правка/применить/отмена/сброс/Esc), экспорт, глоссарий (CRUD), мастер (шаги, пропуск), F1+поиск, выход при прогоне, worker.failed, экспорт-диалог
- [x] T017 `flutter analyze` clean + `flutter test` 60 passed; pytest 44+10 passed

## Converge

- [x] T018 Ручной прогон (live):
  - Мастер первого запуска: на чистом data dir показывается (`show=true` 14 c по логу), пользователь сам прошёл его — настройки записались одним `PUT /api/settings` с `first_run_complete`
  - Экспорт end-to-end: drop главы → перевод всех (2 страницы `done`) → `POST /api/dialog/directory {path}` (хост-выбор) → `POST /api/jobs/export` → в папке появились `test-2.png`, `test-3.png`
  - Удалёнка: `remote_enabled=true` в настройках + запуск БЕЗ `--remote` → «Удалённый API http://127.0.0.1:48765», `remote/status.enabled=true`, код сопряжения выдаётся
  - Экраны/диалоги (рендер, клики, Esc) — покрыты 9 новыми widget-тестами; живьём проверены ранее открытие шестерёнки/глобуса
  - Закрытие окна: штатный выход, сайдкар гаснет, `api.json` удалён, orphan-процессов нет
