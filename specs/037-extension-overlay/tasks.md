# Tasks: Стабильный overlay расширения

## Phase 1: Test Foundation
- [x] T001 Добавить synthetic fixture для contain и переноса того же img в `tests/e2e/test_extension.py`; исходная версия должна воспроизводимо показывать смещение.

## Phase 2: Overlay Geometry
- [x] T002 Вычислять видимый прямоугольник `object-fit/object-position` и размещать UI в отдельном fixed overlay; убрать оборачивание img в `extension/src/content.js` и `content.css`.
- [x] T003 Обновлять геометрию при scroll, resize, смене источника и переносе img; освобождать listeners/observers при удалении.

## Phase 3: Validation
- [x] T004 Проверить 20 циклов, клики, перевод, contain/cover, object-position и повторное открытие; описать подтверждённые ограничения в `docs/EXTENSION.md`.

## Dependencies
T001 → T002 → T003 → T004.
