# Tasks: FastStone quick translate
**Input**: spec.md, plan.md, research.md, data-model.md, contracts/quick.md. Учтено уточнение пользователя: только сервер по IP, протокол расширения.

## Phase 1: Setup
- [x] T001 Создать и проверить спецификацию 016 и checklist в specs/016-faststone-quick-translate/.
- [x] T002 Оформить серверный дизайн, контракты и quickstart в specs/016-faststone-quick-translate/.

## Phase 2: Foundation
- [x] T003 Добавить quick_server_url в src/config.py и src/app/settings.py; raw Bearer хранить отдельно в data/quick-server-token.txt через src/app/quick.py.

## Phase 3: US1 — Приём и серверный автоперевод
Independent test: ошибка среднего файла, один HTTP-запрос перевода одновременно, ноль заданий локальному worker.
- [x] T004 [US1] Проверить очередь, дедупликацию, форматы и отсутствие локального fallback в tests/unit/test_quick.py.
- [x] T005 [US1] Реализовать сессию с RLock и progress 0..100 в src/app/quick.py; протокол расширения и лимит multipart в src/app/quick_remote.py.
- [x] T006 [US1] Добавить локальные API и запрет browser/LAN доступа к путям ПК в src/app/server.py и src/app/web_server.py.

## Phase 4: US2 — Минимальный интерфейс
Independent test: изображение, бейдж и ПКМ без shell; настройка сервера доступна в пустом окне.
- [x] T007 [US2] Добавить widget/state tests в apps/desktop/test/quick_test.dart.
- [x] T008 [US2] Реализовать contain/бейдж/ПКМ/колесо, polling и диалог сервера в apps/desktop/lib/src/quick/quick_app.dart.
- [x] T009 [US2] Реализовать cancel/retry/remove/save в src/app/quick.py и UI-диалоги сохранения в quick_app.dart; DELETE активной задачи отменяет её worker в src/app/remote.py и desktop.py.

## Phase 5: US3 — Общий хост и независимость
Independent test: quick — отдельное настоящее окно; при закрытии сохраняется серверная задача и приём результата.
- [x] T010 [US3] Проверить mode quick и несколько путей с кириллицей в apps/desktop/test/single_instance_test.dart.
- [x] T011 [US3] Реализовать mode и совместимость onPaths в apps/desktop/lib/src/sidecar/single_instance.dart.
- [x] T012 [US3] Реализовать native второе окно, UTF-8 заголовки и show/hide/close в apps/desktop/windows/runner/.
- [x] T013 [US3] Связать --quick, отложенные IPC-запросы и общий сайдкар в apps/desktop/lib/main.dart; child запускает только HTTP-клиент, не ShellState.
- [x] T014 [US3] Реализовать копирование кадра в отдельный проект редактора с проверкой черновика в src/app/quick.py, main.dart и quick_app.dart.

## Phase 6: US4 — Багрепорт
Independent test: заметка и материалы без LLM/Bearer-секрета; legacy-server явно отмечен.
- [x] T015 [US4] Проверить пустую заметку, секреты, JSON и результат в tests/unit/test_quick.py.
- [x] T016 [US4] Реализовать локальный отчёт и диалог в src/app/quick.py и quick_app.dart; добавить opt-in server diagnostics без смены обычного контракта в remote.py/desktop.py.

## Phase 7: Validation
- [x] T017 Обновить docs/APP.md для серверного --quick, сопряжения и FastStone, сохранив E.
- [x] T018 Выполнить pytest, Flutter tests/analyze и Windows build; записать результаты в specs/016-faststone-quick-translate/validation.md.
- [ ] T019 Пройти ручную FastStone-цепочку с реальным сервером и кодом сопряжения; записать фактические ограничения в specs/016-faststone-quick-translate/validation.md.

## Dependencies and strategy
T001 -> T002 -> T003 -> US1; US2/US3 используют US1; US4 использует сессию и необязательную диагностику сервера. MVP — US1+окно US3+изображение US2. API-тесты независимы от Flutter; widget tests независимы от native build; IPC test независим от LAN. В рамках каждого общего файла изменения последовательны. Дополнительная параллельная реализация не требуется.

## Phase 8: Convergence
- [ ] T020 Завершить T019: после отдельно разрешённого безопасного деплоя и получения кода сопряжения пройти FastStone Alt+2/E → http://192.168.88.41:8765, проверить изображения/ПКМ/офлайн/багрепорт и записать результат в specs/016-faststone-quick-translate/validation.md per US1/AC1, SC-001, SC-006, T019 (partial, HIGH). Код и сборка готовы; текущая проверка ограничена синтетическим сервером и live health.
