# Tasks: 028-editor-ux

## Spec & plan

- [x] T001 `spec.md` (US1–US9, FR-001…FR-013, Research по `job.progress`) + `plan.md` (9 правок, тесты, Converge)

## Python

- [x] T002 `settings.py`: `dock_position` (normalize/`to_dict`); pytest: нормализация и round-trip

## State

- [x] T003 `workspace_state.dart`: `_mergeProgress` для `job.progress` (`running`, progress/stage, `error: ''`)
- [x] T004 Оптимистичный `translate()` (`_markQueued` до POST, `skip_ready: true`, откат при ошибке)
- [x] T005 `dockAtTop` + `setDockPosition()` (оптимистично, PUT без `busyAction`)
- [x] T006 `view_transform.dart`: `clamped(..., verticalMargin)`; `viewer_state.dart`: 0.25 в `_recompute`/`zoomStep`/`panBy`
- [x] T007 `viewer_shortcuts.dart`: Ctrl+Enter / Ctrl+Shift+Enter

## UI

- [x] T008 `viewer_dock.dart`: `ViewerDockHost`, ручка `viewer-dock-grip`, drag и снап ⅓; `shell.dart` — хост
- [x] T009 `pages_rail.dart`: «Очередь», иконочные пауза/стоп, полоска 4 px, строка 83, поиск 32, подвал без «Перевести всё»
- [x] T010 `page_thumb.dart`: 55×75, `targetWidth` 110; `top_bar.dart`: пункт «Перевести всё»
- [x] T011 Высоты: `kFieldHeight` 32 (`theme`, `widgets`, `InspectorInput`, F1, глоссарий, API-ключ, hex, экспорт), «Добавить регион» 48
- [x] T012 Макеты `web/mockups/next`: CSS 32/48/55×75, editor/empty без «Перевести всё», batch — «Очередь» и иконочные кнопки

## Tests

- [x] T013 `workspace_state_test.dart`: `job.progress` → `running`; оптимистичный translate + `skip_ready` + откат; `setDockPosition` PUT
- [x] T014 `canvas_geometry_test.dart` + `viewer_state_test.dart`: вертикальный запас ¼ и дефолт 0
- [x] T015 `widget_test.dart`: поиск 32, нет `pages-translate-all`, оптимистичная очередь, Ctrl+Enter/Ctrl+Shift+Enter; `viewer_widget_test.dart`: кнопка 48, drag дока, превью/строка

## Verify & Converge

- [x] T016 `flutter analyze` + `flutter test` (118 passed, +6 к 027)
- [x] T017 pytest полный: 398 passed, 1 skipped, 1 pre-existing (`test_text_style::test_rotated_layer_stays_on_block_center` — падает и на чистом HEAD из 026/027)
- [x] T018 Сборка `build-windows.ps1 -SkipModels` → dist + `ImageLocalizationTool-1.0.0-windows-x64-setup.exe`; `deploy-windows.ps1` (robocopy exit=3, models сохранены); живой smoke на задеплоенном exe (изолированный `ILT_DATA_DIR`): handshake, `GET /api/bootstrap` с `dock_position` = bottom, закрытие хоста без orphan-процессов

## Итог и отклонения

- Причина «не начата» — `job.progress.status` воркера (человекочитаемая стадия) нормализовался в `idle`; фикс — веб-паритет `_mergeProgress`, Python не тронут (только аддитивный `dock_position`).
- Позиция дока пишется существующим `PUT /api/settings` без `busyAction`: настройка некритичная, ошибка PUT не поднимает полосу.
- «Всё» шлётся с `skip_ready: true` (паритет веба): готовые страницы не переделываются.
- Пустой запас канваса — доля высоты листа (0.25), дефолт 0 сохранил все прежние тесты геометрии.
- Полная batch-раскладка `main-batch`, семантика режимов и хоткеи Ctrl+O/S/K остались вне рамок фичи.
