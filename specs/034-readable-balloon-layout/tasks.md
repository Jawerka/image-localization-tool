# Tasks
## Phase 1: Setup
- [x] T001 Зафиксировать требования и план в specs/034-readable-balloon-layout/.
## Phase 2: Tests
- [x] T002 [US1] Добавить регрессии масок в tests/unit/test_bubble_contour.py.
- [x] T003 [US2] Добавить проверки переноса по форме в tests/unit/test_bubble_layout.py.
## Phase 3: US1 — Mask
- [x] T004 [US1] Перенести принятый алгоритм в src/components/bubble_contour.py и проверить совпадение масок.
## Phase 4: US2 — Layout
- [x] T005 [US2] Реализовать раскладку в src/components/bubble_layout.py и подключить в src/components/typesetter.py.
- [x] T006 [US2] Сравнить минимум три метода через scripts/eval_balloon_layout.py; сохранить output/layout-study.
## Phase 5: Validation
- [x] T007 Выполнить регрессионные тесты и осмотреть все страницы, записать docs/BALLOON_LAYOUT_RESULTS.md.
- [x] T008 Сверить реализацию со spec.md и plan.md через speckit-converge.

Dependencies: T001 → T002/T003 → T004 → T005 → T006 → T007 → T008.
Parallel opportunities: независимые тесты T002/T003; выполнение в этой сессии последовательное.
Strategy: сначала маски (MVP), затем геометрия и перенос, затем сравнение и регрессии.
