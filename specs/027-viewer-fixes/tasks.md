# Tasks: 027-viewer-fixes

## Spec & plan

- [x] T001 `spec.md` (US1–US6, FR-001…FR-010, Research по Windows-DPI) + `plan.md` (6 правок, тесты, Converge)

## Canvas

- [x] T002 `canvas_painter.dart`: убрать `translate/scale` из `paint()` (единственный владелец transform — `InteractiveViewer`), актуализировать docstring; `canvas_view.dart` — комментарий владельца
- [x] T003 Space-рука: `MouseRegion` внутрь `AnimatedBuilder`, pan по `session.spaceDown`, курсор `grab`, кружок кисти скрыт, `setTool` не вызывается; `viewer_shortcuts.dart` — keyup Space без залипания при вводе

## Theme

- [x] T004 `app.dart`: `MaterialApp(theme/darkTheme/themeMode)` из `buildIltTheme` (platform brightness через `platformDispatcher`)

## Rail

- [x] T005 `workspace_state.dart`: `loadThumbnail()` через `IltApi.getBytes`; `ui/page_thumb.dart` (LRU ~64, ключ `id|status`, `targetWidth ≈ 84`, плейсхолдер, `pages-thumb-{id}`)
- [x] T006 `pages_rail.dart`: строка ~66 px с миниатюрой 42×58 и статус-точкой, номер/имя/статус/прогресс/меню; reorder и клики сохранены
- [x] T007 Высоты: поиск 28 → 46; `inspector_rail.dart` «Добавить регион» 28 → 56 (без compact)
- [x] T008 Макеты `web/mockups/next`: `.in2--tall` (46) + `.b2--tall` (56) в `components-v2.css`; классы в `main-editor.html` (поиск, кнопка)

## Tests

- [x] T009 `canvas_painter_test.dart`: пиксель штриха при `scale≠1` и сдвиге (защита от двойного transform)
- [x] T010 `viewer_widget_test.dart`: Space → `grab`, tool не изменился, `viewer-brush-cursor` скрыт; keyup возвращает; `inspector-add-region` = 56
- [x] T011 `screens_test.dart`: dark/light — оверлей настроек и диалог «Неприменённые правки» следуют теме; `widget_test.dart`: `pages-thumb-{id}`, `pages-search` = 46

## Verify & Converge

- [x] T012 `flutter analyze` + `flutter test` (109 passed, +3 к 026); pytest полный: 397 passed, 1 skipped, 1 pre-existing (`test_text_style::test_rotated_layer_stays_on_block_center` — падает и на чистом HEAD из 026)
- [x] T013 Сборка: `build-windows.ps1 -SkipModels` → dist + `dist\ImageLocalizationTool-1.0.0-windows-x64-setup.exe`; `deploy-windows.ps1` зеркалит `D:\Documents\apps\ImageLocalizationTool` (robocopy exit=3 = OK, models сохранены)
- [x] T014 Живой прогон (автоматизированная часть на задеплоенном exe, изолированный `ILT_DATA_DIR`): старт 1,29 с, `api.json`, `GET /api/bootstrap` (version 1.0.0); `POST /api/drop` импортировал `test-1.jpg` (проект, 1 страница); закрытие окна — хост и сайдкар завершены, `api.json` удалён, orphan-процессов нет. Интерактивные проверки (вписать/мазок/Space/тема/превью) покрыты пиксельным и виджет-тестами; визуальная приёмка — за пользователем на своей машине.

## Итог и отклонения

- Причина «маленького листа» и «мазка выше-левее» — двойной transform (painter применял ту же матрицу, что и `InteractiveViewer` → scale² и двойной сдвиг), а не Windows-DPI: в спеке зафиксирован вывод research (PerMonitorV2, логические пиксели; масштаб текста геометрию не двигает).
- Ключ миниатюры включает статус (`id|status`) — после прогона сервер перезаписывает `thumb`, превью обновляется без ручного сброса.
- Space-рука больше не читает `HardwareKeyboard` напрямую: состояние идёт через `session.spaceDown` (guard ввода/оверлея), keyup сбрасывается даже при фокусе в поле ввода.
- Режимы «Отбор | Ретушь | Прогон» кодом не менялись (решение финального плана); полная семантика — отдельная фича.
- Интерактивная часть живого прогона (визуальная сверка темы/превью/высот) оставлена пользователю: тесты подтверждают поведение, автоматизировать клики без захвата ввода нельзя.
