# Tasks: Наведение и качество страниц
## Phase 1: Setup
- [X] T001 Зафиксировать требования и дизайн в specs/014-hover-page-quality/.
## Phase 2: Foundational
- [X] T002 Сохранить автономный baseline новых JPG в output/hover-page-quality/.
## Phase 3: US1
- [X] T003 [US1] Добавить popup-регрессии в tests/e2e/test_extension_safe.py и воспроизвести дефект.
- [X] T004 [US1] Исправить hit testing, задержку и неподвижное перекрытие в extension/src/safe-content.js и extension/src/inline-content.js.
- [X] T005 [US1] Выполнить E2E и JavaScript проверки расширения.
## Phase 4: US2
- [X] T006 [US2] Выявить общие причины дефектов baseline и исправить в src/components/ с релевантными tests/unit/.
- [X] T007 [US2] Повторить автономную обработку двух новых и минимум трёх старых страниц.
## Phase 5: Polish
- [X] T008 Записать измерения и визуальные ограничения в docs/BENCHMARK_RESULTS.md.
- [X] T009 Проверить соответствие spec/plan/tasks через speckit-converge.
## Dependencies
T001 → T002; T003 → T004 → T005; T002 → T006 → T007 → T008 → T009.
## Parallel examples
Чтение кода наведения и baseline независимы; LLM-прогоны строго последовательны.
## Implementation Strategy
Сначала исправить и проверить наведение, затем общие причины качества; деплой и публикация не выполняются.

