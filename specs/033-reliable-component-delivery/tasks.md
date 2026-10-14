# Tasks: Надёжная докачка компонентов

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/preparation-api.md.
**Tests**: обязательные fault-injection и транзакционные проверки по FR-015.

## Phase 1: Setup

- [x] T001 Оформить спецификацию и дизайн в specs/033-reliable-component-delivery/.
- [x] T002 Зафиксировать runtime-каталог обеих платформ и ресурсный каталог в locks/runtime-catalog.json и src/app/component_manifest.json; Argos wheel и провенанс в assets/.

## Phase 2: Foundational

- [x] T003 Реализовать writable component-root и настройки загрузки в src/utils/paths.py, src/config.py, src/app/settings.py.
- [x] T004 Написать сетевые fault-injection тесты в tests/unit/test_downloads.py.
- [x] T005 Реализовать общий кэш, Range/retry/pausing, OS-lock и disk-check в src/app/downloads.py.

## Phase 3: US2 — Продолжение

**Independent Test**: обрыв/Range/200/416/429/503/corruption локальным HTTP-сервером.
- [x] T006 [US2] Подключить общий загрузчик к runtime и моделям в src/app/runtime.py, model_manager.py.
- [x] T007 [US2] Реализовать persisted queue/state и pause/resume в src/app/preparation.py.
- [x] T008 [US2] Добавить API/SSE snapshot и сериализацию legacy задач в src/app/server.py.
- [x] T009 [US2] Покрыть сохранение после перезапуска, immutable selection и busy в tests/unit/test_preparation.py.

## Phase 4: US3 — Установка и восстановление

**Independent Test**: новая ревизия не меняет старую при отказе проверки.
- [x] T010 [US3] Добавить inventory/revision, чистые probes и атомарную активацию в src/app/runtime.py, component_check.py.
- [x] T011 [US3] Покрыть транзакции/legacy/corruption/concurrency в tests/unit/test_runtime.py и test_component_catalog.py.
- [x] T012 [US3] Убрать импорт torch для статуса parent и обеспечить новую worker-активацию в src/app/runtime.py, server.py, worker.py.
- [x] T013 [US3] Добавить cu130, платформенные рекомендации и любой torch conflict в src/app/hardware.py, deploy.py и Flutter экранах; tests/unit/test_hardware.py, test_deploy_cli.py.

## Phase 5: US1 — Подготовка и ресурсы

**Independent Test**: выбранный offline en→ru готовит OCR/язык/MiniSBD и работает без сети.
- [x] T014 [US1] Реализовать каталог ресурсов и checked model/language install в src/app/component_catalog.py, model_manager.py.
- [x] T015 [US1] Передавать внешние модели RapidOCR и запретить загрузку языка при переводе в src/components/rapid_ocr.py, translator.py.
- [x] T016 [US1] Убрать веса RapidOCR/дополнительные шрифты из базы и усилить audit в ImageLocalizationTool.spec, scripts/smoke_dist.py.
- [x] T017 [US1] Подключить preparation snapshot/reconnect в apps/desktop/lib/src/state/secondary_state.dart, shell_state.dart, api/sse.dart.
- [x] T018 [US1] Создать общий preparation_panel и обновить мастер/настройки в apps/desktop/lib/src/ui/.
- [x] T019 [US1] Покрыть UI выбора режима/объёма/продолжения в apps/desktop/test/preparation_test.dart.

## Phase 6: US4 — Простой релиз

**Independent Test**: обычный release не resolve; Publish отвергает подмену candidate.
- [x] T020 [US4] Добавить wheel-base/cu130 и явное обновление локов в scripts/build_runtime_locks.py, build-runtime-locks.ps1; сохранить cu130 lock/catalog.
- [x] T021 [US4] Сделать идентичные manifest до упаковки и убрать позднюю merge в scripts/build-runtime-manifest.py, publish-release.ps1, .github/workflows/release.yml.
- [x] T022 [US4] Добавить Prepare/Publish отчёт и неизменность candidate в scripts/release.ps1, release_candidate.py; tests/unit/test_release_candidate.py.
- [x] T023 [US4] Перевести e2e на fixed catalog/cache и anonymous gate в scripts/e2e-runtime-local.ps1, check_release.py.

## Phase 7: Polish

- [x] T024 Обновить README.md, docs/APP.md, RELEASE_NOTES_1.0.1.md и research.md по финальной реализации.
- [x] T025 Прогнать полный pytest, Flutter analyze/test и record результатов в specs/033-reliable-component-delivery/quickstart.md.
- [ ] T026 Выполнить Windows frozen CPU/Argos/OCR и GPU smoke, аудит base; Linux smoke через CI; отметить фактические ограничения в quickstart.md.
- [ ] T027 Прогнать speckit-converge и закрыть выявленные gaps в tasks.md.

## Dependencies & Execution Order

T001→T002/T003→T004/T005→US2→US3→US1→US4→Polish. Изолированные исследования каталогов/Flutter/релиза выполняются research agents согласно speckit-plan, реализации выполняются последовательно. Минимальный проверяемый шаг — общий загрузчик; конечный scope включает все истории, не ограничивается MVP.

## Parallel Examples

Независимые чтения и тесты разных модулей можно запускать одновременно; изменения общих runtime/server файлов выполняются последовательно. Отдельные research agents исследуют ресурсы, релиз и Flutter без записи файлов.
