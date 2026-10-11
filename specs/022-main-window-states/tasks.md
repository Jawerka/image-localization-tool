# Tasks: 022-main-window-states

## Spec & plan

- [x] T001 `spec.md` (US1 empty, US2 editor, US3 batch, US4 frame actions; split 022–025 fixed) + `plan.md`

## State

- [x] T002 `lib/src/state/workspace_state.dart`: модели `ProjectInfo`/`PageRow`/`RecentEntry`/`BatchCounts`; `applyBootstrap`/`applyCollection`/`applyEvent`; выбор, поиск, фильтр «Проблемы»
- [x] T003 Действия workspace: `importPaths`, `openRecent`, `clearRecent`, `translate(page|all)`, `pause/resume/cancel/retryErrors`, `removePages`, `reorderPages`, `closeProject(force)`, `loadPackage`/`savePackage`; ошибки → `errorText`
- [x] T004 `shell_state.dart`: владение `WorkspaceState`, привязка API, пересылка SSE-событий (с разворачиванием конверта `{type, payload}`), ре-нотификация

## UI

- [x] T005 `lib/src/ui/labels.dart`: RU-строки статусов/этапов (точь-в-точь как `web/js/state.js`)
- [x] T006 `lib/src/ui/top_bar.dart`: меню «Файл», проект+счётчик, чип языков, сегмент режимов, job pill + стоп, «Перевести»/«Экспорт»/«Настройки» с правилами включения
- [x] T007 `lib/src/ui/pages_rail.dart`: список страниц (номер, имя, статус, прогресс, главные заголовки), поиск, мультивыбор, меню строки (выше/ниже/удалить), drag-reorder, batch-блок, подвал «N из M готово» + «Перевести всё» + «Проблемы»
- [x] T008 `lib/src/ui/scene.dart`: пустое окно (дропзона + недавние + «Очистить»), карточка страницы (023 заменит), stage pill при batch
- [x] T009 `lib/src/ui/inspector_rail.dart` + `dock.dart` + `status_bar.dart`: ожидающие состояния, инструменты (disabled в batch), чипы LLM/device/version
- [x] T010 `lib/src/ui/file_dialogs.dart`: обёртка `file_selector` (файлы/папка/пакет туда-сюда); `shell.dart` — композиция регионов, strip ошибок; `main.dart` — drop второго запуска применяется к workspace
- [x] T011 `lib/src/app.dart`: прокинуть workspace в `ShellScreen`

## Tests & CI

- [x] T012 `test/workspace_state_test.dart`: bootstrap→страницы; collection merge; события (`page.updated` прогресс, `worker.failed`); счётчики; действия шлют правильные запросы (MockClient)
- [x] T013 `test/widget_test.dart`: пустое окно (дропзона, недавние, disabled-кнопки), редактор (страницы, подвал, выбор, **сквозной SSE-кадр сервера**), batch (pill, пауза/стоп, сцена), dirty-close strip, ошибка старта
- [x] T014 `flutter analyze` clean + `flutter test` 46 passed

## Converge

- [x] T015 Ручной прогон хоста (debug exe, изолированный `ILT_DATA_DIR`, тестовая папка): результаты
  - Пустое окно → второй запуск с путём папки (single-instance → `/api/drop`) → проект «chapter», 4 страницы; UI первого окна обновился
  - «Перевести» из UI (клики) → batch-состояние: job pill, batch-блок с счётчиками, stage pill, док заблокирован, inspector «страница в работе»
  - Найден и исправлен баг: `ShellState` передавал в workspace конверт `{type, payload}` вместо `payload` — live-события игнорировались; после фикса ход 002.jpg `reset→running→готово` наблюдался в UI без перезагрузки (SSE)
  - Pause/resume/cancel против живого сайдкара: `paused: true/false`, после cancel все строки снова `idle`
  - Закрытие окна: хост и сайдкар умирают ≤ 3 с, `api.json` удалён, orphan-процессов нет
  - Attach-режим: чужие сайдкары не убиваются при выходе хоста
  - Дополнительно исправлено: `_forwardPaths` теперь применяет ответ `/api/drop` к workspace (второй запуск виден в первом окне)
