# Tasks: 023-viewer

## Spec & plan

- [x] T001 `spike.md` (замер jank'а: 5 вариантов сцены, решение «без RepaintBoundary») + `spec.md` (US1–US6) + `plan.md`

## Model & state

- [x] T002 `lib/src/model/page_document.dart`: `PageDocument`/`Region`/`Stroke`, нормализация ответа API (неизвестные поля сохраняются), `clampBox`, `blankRegion`, `nextRegionId`, `contentKey`, флаги (`skip/overflow/sfx`); `lib/src/model/view_transform.dart`: fit/fit-width/шаги 5 %/зум к точке/кламп
- [x] T003 `lib/src/state/viewer_state.dart` (ядро): загрузка `GET /api/pages/{id}` с токеном против гонок, `selectedRegionId`, `tool`/`view`/`curtain`/`showBoxes`/`showMask`/`brushSize`, кэш `ui.Image` (LRU 16, ключ `pageId|kind|version`, fallback на прошлую версию до декода новой), `hasFreshImage`, `CanvasSession` (матрица + предпросмотры жестов)
- [x] T004 Черновик и сохранение: `editDocument({deferApply, coalesce})`, история по страницам (лимит 50), undo/redo с baseline-семантикой, `pendingBody`, `scheduleSave`/`flush` с debounce, `commitDeferredEdits`/`discardDeferredEdits`, `whenSaved`, 409 → ретрай с версией из тела ошибки, полоса ошибки + перечитка документа
- [x] T005 `workspace_state.dart`: владение `ViewerState`, загрузка detail при выборе/смене коллекции, `reloadIfClean` по `page.updated` (версии картинок), страж ухода (диалог применить/отменить/остаться), сессия `editor` в `package/save|load`, `stepPage`, `focusNextProblem`, `PageRow.overflow`

## Canvas UI

- [x] T006 `lib/src/ui/viewer/canvas_painter.dart`: лист (`original|result|mask`, multiply + 0.5), шторка сравнения (клин, линия, подписи, ручка), рамки (номера, флаги, выделение, 8 ручек + поворот, точки warp), драфт/перенос/штрихи/лассо, компенсация `1/scale`
- [x] T007 `lib/src/ui/viewer/canvas_view.dart`: `Listener` + `InteractiveViewer` (жесты выкл.) + painter; панорама (средняя/пробел/«Рука»), Ctrl+колесо/колесо, кисть/лассо, создание/перенос/размер/поворот/warp, шторка, курсор кисти, хит-тест 8 px
- [x] T008 `lib/src/ui/viewer/viewer_pane.dart`: композиция (канвас/чипы/стрелки/пилюля этапа), `done_pill.dart` с перетаскиванием и смещением в сессии
- [x] T009 `lib/src/ui/viewer/viewer_dock.dart`: виды, слои L/M, инструменты, попап кисти 1–64, undo/redo, зум
- [x] T010 `lib/src/ui/viewer/viewer_shortcuts.dart`: V/R/B/P/H, 1/2/3, L/M, `[`/`]`, Ctrl+Z/Y, Ctrl+0/1, PgUp/PgDn, стрелки (страницы/сдвиг Shift/Alt-размер), N, Delete, пробел, Esc; ввод/модалки не перехватываются
- [x] T011 `scene.dart` → `ViewerPane`; `shell.dart` → `ViewerDock` + полоса ошибок вьюера; `app.dart` → обработчик клавиш канваса и диалог неприменённых правок; удалён placeholder `ui/dock.dart`

## Tests & CI

- [x] T012 `page_document_test.dart` + `viewer_state_test.dart`: нормализация/клампы/создание региона, правки/история/undo/redo, defer/discard/commit, PUT `/api/pages/{id}/document` с `base_version`, 409-ретрай, страж ухода, декод изображений (1×1 PNG)
- [x] T013 `canvas_geometry_test.dart` + `viewer_widget_test.dart`: матрица/шаги/зум-к-точке/кламп/хит-тест/ручки/warp; виджет-тесты канваса, дока, пилюли, диалога ухода
- [x] T014 `flutter analyze` clean + `flutter test` 89 passed (было 60)

## Converge

- [x] T015 Ручной/сквозной прогон и правки:
  - `tool/viewer_smoke.dart` против живого сайдкара (изолированный `ILT_DATA_DIR`, `test-img/test-1.jpg`): импорт → 15 регионов → лист 600×900 и маска из API → штрих → «Готово» (`PUT …/document`) → версия 2→3 → перевёрстка → свежее изображение новой версии; `SMOKE_DONE failures=0`, страницы без orphan, штрих в `page.json` (v4)
  - Найдено и исправлено в прогоне: `_flush` ошибался адресом (`PUT /api/pages/{id}` → 405) — правильный контракт `PUT /api/pages/{id}/document` (как `web/js/api.js`);
  - Найдено и исправлено: строгий `utf8.decoder` на stdout/stderr сайдкара бросал `FormatException` на русских логах в консольной кодировке — декодер переведён в `allowMalformed: true`
  - Widget-тесты 022 обновлены под 023 (карточка страницы заменена канвасом, док только при активной странице)
- [ ] T016 (остаток) Опционально: повторный профильный прогон `viewer_jank_spike.dart` с добавленным вариантом штрихов маски; ручной проход реального окна (клики) — по желанию, API-цикл и UI-жесты покрыты автотестами; `style.html/sfx.html`-режимы инспектора ждут 024

## Отклонения от веба (зафиксировано)

- Геометрия (перенос/размер/поворот/warp) идёт в черновик до «Готово» (в вебе часть правок автосохраняется); причина — один цикл перевёрстки на «Готово» и консистентность US6. Текстовое автосохранение остаётся 024.
- Оверлеи рисуются одним `CustomPaint` без `RepaintBoundary` (решение спайка); рамки/ручки/подписи компенсируются `1/scale`, ручки размера видимы (в вебе — невидимые зоны).
- Поворот хранится в `style.rotation` и не вращает экранную рамку (как в вебе).
