# Tasks: Более толстая автообводка
## Phase 1: Setup
- [x] T001 Изучить единые пути подбора/рисования в src/components/typesetter.py и free_text_layout.py.
- [x] T002 Запустить исходный полный прогон 21 страницы, сохранять OCR/перевод и чистый рабочий слой в output/thick-outline-tests/before.
## Phase 2: US1
- [x] T003 [US1] Реализовать усиление на небелом фоне и единый запас в src/components/typesetter.py.
- [x] T004 [US1] Проверить фоны, ручные режимы, запас и повторную вёрстку в tests/unit/test_nonwhite_outline.py.
## Phase 3: US2
- [x] T005 [US2] Завершить полный перевод 21 страницы и повторную вёрстку в output/thick-outline-tests/after.
- [x] T006 [US2] Осмотреть реальные результаты и переполнения, собрать сравнение в столбик и архив PNG в output/thick-outline-tests.
## Phase 4: Polish
- [x] T007 Проверить релевантные тесты и документацию; записать результаты в docs/BENCHMARK_RESULTS.md.
- [x] T008 Сверить реализацию со spec.md/plan.md/tasks.md через speckit-converge.
## Dependencies
T001→T002→T003→T004; результаты T005 поступают последовательно, T006 зависит от полного набора. LLM-запросы выполняются по одному. Последняя фаза после визуальной проверки.
