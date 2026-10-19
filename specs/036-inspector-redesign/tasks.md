# Tasks: Современный инспектор
## Phase 1: Setup
- [x] T001 Изучить текущую карточку и контракт в web/js/inspector.js.
## Phase 2: Foundation
- [x] T002 Зафиксировать совместимость в specs/036-inspector-redesign/contracts/inspector.md.
## Phase 3: US1 — Текст
Проверка: ввод и сохранение оригинала/перевода.
- [x] T003 [US1] Перегруппировать поля и действия текста в web/js/inspector.js.
## Phase 4: US2 — Оформление
Проверка: стиль и раскрытие секций переживают редактирование.
- [x] T004 [US2] Сгруппировать оформление и положение в web/js/inspector.js; сохранить position в web/js/inspector_render.js.
## Phase 5: Polish
- [x] T005 Добавить адаптивные стили в web/css/inspector.css и подключить в web/index.html.
- [x] T006 Проверить JS и браузерные сценарии; результаты записать в specs/036-inspector-redesign/quickstart.md.
## Dependencies
T001 → T002 → T003 → T004 → T005 → T006.
## Parallel opportunities
US1 и US2 меняют один файл, выполняются последовательно. Визуальная проверка обеих тем независима после реализации.
## Implementation strategy
Сначала рабочая разметка текста, затем оформление, затем визуальная проверка и converge.

## Phase 6: US3 — Геометрия
- [x] T007 [US3] Добавить линии сетки и перспективы, Shift-перемещение и перемещение preview в web/js/viewer.js.
- [x] T008 [US3] Добавить вход в редактирование геометрии и корректный запрос preview в web/js/inspector.js.
- [x] T009 [US3] Проверить mesh drag и предпросмотр браузерными тестами в tests/e2e/test_ui_smoke.py.
- [x] T010 Проверить клавиатурный переход по узлам сетки и защитить свежий ввод при повторном переводе через ожидание сохранения и `base_version`; покрыть API, worker и UI-тестами.
