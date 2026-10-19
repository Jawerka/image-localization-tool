# Tasks: Независимое размещение текста

## Phase 1: Data Contract
- [x] T001 Добавить валидируемое поле `text_position` с identity default в `src/models.py`; проверить round-trip и старые документы.
- [x] T002 Изменить Typesetter так, чтобы положение выводимого текста применялось после layout и не сдвигало область маски; сравнить identity pixels.

## Phase 2: Transparent Layer Preview
- [x] T003 Возвращать прозрачный RGBA-слой, origin и полные bounds из общего renderer без повторного layout.
- [x] T004 Расширить preview-ответ координатами/revision; сохранить прежний endpoint-ответ для старых вызовов.
- [x] T005 Собирать crop очищенной страницы и текстовый слой в preview без фонового прямоугольника; отбрасывать устаревшие ответы.

## Phase 3: Canvas Gesture
- [x] T006 Добавить drag с локальным draft, Escape/pointercancel rollback и одной записью undo; bbox и маску не менять.
- [x] T007 Проверить export/preview alignment, старые документы и быстрые последовательные preview.

## Verification
- `tests/unit/test_models.py`, `tests/unit/test_app_document.py`, `tests/unit/test_typesetter.py`.
- `tests/unit/test_app_server.py::test_preview_region_echoes_revision_and_includes_moved_text_bounds`.
- `tests/e2e/test_ui_smoke.py::test_text_layer_moves_without_changing_recognition_box`.
- `tests/unit/test_text_mesh.py` and `tests/js/test_text_mesh.mjs` share the same numerical fixtures for mesh v2.
- Full verification: `pytest -q` → 564 passed, 1 skipped; `npm run test:js` → 49 passed; UI + extension → 9 passed.
