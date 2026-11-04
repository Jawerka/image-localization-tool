# Tasks: Безопасный деплой

## Phase 1: Setup
- [x] T001 Проверить сервер и действующие скрипты, зафиксировать проблему в research.md.
## Phase 2: US1 — Dry run
- [x] T002 [US1] Добавить настоящий read-only план в scripts/lan_deploy.py и scripts/lan_deploy_remote.py.
- [x] T003 [US1] Добавить Windows dry run и allowlist в scripts/deploy-windows.ps1.
- [x] T004 [US1] Проверить отсутствие записей и сохранность placeholder-папок в tests/unit/test_deploy_scripts.py и test_lan_deploy.py.
## Phase 3: US2 — Применение
- [x] T005 [US2] Реализовать backup, валидацию TAR/путей/хешей и откат LAN в scripts/lan_deploy_remote.py.
- [x] T006 [US2] Прогнать dry run и развернуть CT113; отчёты в output/safe-deployment/.
- [x] T007 [US2] Проверить health и 1460 файлов проектов относительно backup, сохранить server-data-verification.json.
## Phase 4: Polish
- [x] T008 Записать обязательное правило в AGENTS.md и .cursor/rules/deployment-dry-run.mdc.
- [x] T009 Завершить негативные тесты архива, документов и сверку требований в docs/DEPLOYMENT_SAFETY.md.

Проверка соответствия: FR-001–006 и SC-001–004 выполнены. 32 целевых теста, Ruff и проверка diff прошли. Реальный LAN-deploy завершён; заключительный dry run показывает 0 отличий. Конфигурация и 1460 файлов проектов сверены с backup. Незакрытых требований в этом объёме нет; tasks.md не требует дополнительных convergence-задач.

## Dependencies

Сначала план/проверка, затем backup и применение, затем приёмка. Новые изменения артефактов требуют повторного плана. Тесты источника/назначения и rollback независимы и выполняются вместе.
