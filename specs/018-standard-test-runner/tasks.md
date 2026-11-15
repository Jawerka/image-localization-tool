# Tasks: Стандартный прогон
## Phase 1: Setup
- [x] T001 Зафиксировать спецификацию/план/контракт в specs/018-standard-test-runner/.
## Phase 2: US1 Автономная очередь
- [x] T002 [US1] Реализовать выбор набора, снимки, worker, тайм-аут и отчёты в scripts/test_images.py.
## Phase 3: US2 Продолжение
- [x] T003 [US2] Реализовать хеш-проверки, retry-errors, блокировку и статусы в scripts/test_images.py.
## Phase 4: US3 Галерея
- [x] T004 [US3] Общий шаблон scripts/templates/review_gallery.html и обновление прежней галереи без потери оценок.
## Phase 5: Validation
- [x] T005 Проверить очередь/аварии/resume в tests/unit/test_test_images.py и JSON в tests/js/test_review_gallery.mjs.
- [x] T006 Документировать сценарий в docs/TEST_IMAGE_RUNNER.md и выполнить малый smoke/resume.
Dependencies: T001 → T002 → T003 → T004 → T005 → T006. MVP: US1. Работа последовательная, делегирования нет.

## Phase 6: Явные файлы и консоль
- [x] T007 [US1] Добавить --images/--list-file, внешние файлы, проверку списка и передачу фоновой очереди в scripts/test_images.py (FR-009).
- [x] T008 [US1] Добавить вывод стадий и ожидания в консоль, ошибки и итоговые счётчики в scripts/test_images.py (FR-010).
- [x] T009 Проверить новые варианты и обновить AGENTS.md, docs/TEST_IMAGE_RUNNER.md и tests/unit/test_test_images.py.
