# Tasks: Ретушь светлых букв
## Phase 1: Setup
- [x] T001 Зафиксировать исходный LLM-прогон в output/3419871-check/llm-before и причину в research.md.
## Phase 2: Foundational
- [x] T002 Сохранить фиксированные маски прежнего набора в output/3419871-check/regression-before.json.
## Phase 3: US1
- [x] T003 [US1] Добавить проверки цветных фонов и ложных светлых компонент в tests/unit/test_retouch_ink.py.
- [x] T004 [US1] Исправить подтверждение в src/components/retouch_ink.py и интеграцию в text_segmenter.py/adaptive_text.py при необходимости.
- [x] T005 [US1] Повторить фиксированную очистку и осмотреть результат в output/3419871-check/.
## Phase 4: US2
- [x] T006 [US2] Выполнить полный LLM-прогон и осмотреть перевод в output/3419871-check/llm-after.
- [x] T007 [US2] Проверить прежние маски и релевантные тесты; сохранить отчёт в output/3419871-check/.
## Phase 5: Polish
- [x] T008 Записать результаты и ограничения в docs/BENCHMARK_RESULTS.md и specs/008-light-bubble-retouch/spec.md.
- [x] T009 Выполнить speckit-converge относительно spec.md, plan.md, tasks.md.
## Dependencies
T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009. Независимые тесты могут выполняться вместе. MVP — US1, затем полный прогон US2. Изменения одних компонентов последовательны.

## Phase 6: Локальный деплой по запросу пользователя
- [x] T010 Собрать frozen sidecar и portable ZIP, проверить установленный код в output/3419871-check/deploy/embedded-code.json.
- [x] T011 Развернуть Windows-установку и проверить запуск; результаты в output/3419871-check/deploy/result.json.
- [x] T012 Исправить обнаруженную потерю данных при зеркалировании placeholder-папок в scripts/deploy-windows.ps1; добавить реальные проверки robocopy в tests/unit/test_deploy_scripts.py.
- [x] T013 Восстановить найденные пользовательские данные, сверить настройки и проекты, записать ограничения восстановления в output/3419871-check/deploy/DEPLOYMENT.md.
