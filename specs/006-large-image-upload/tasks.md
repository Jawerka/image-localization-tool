# Tasks: Большие изображения

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/upload.md.

## Phase 1: Setup
- [x] T001 Создать ветку и артефакты specs/006-large-image-upload/.
## Phase 2: Foundational
- [x] T002 Проверить конституцию, ignore-файлы и существующий контракт src/app/remote.py.
## Phase 3: User Story 1
Цель: принять оригинал >20 МиБ без изменения. Независимая проверка: реальная HTTP-загрузка PNG 29 865 297 байт.
- [x] T003 [US1] Поднять потолок до 64 МиБ и добавить max_body_bytes в health в src/app/remote.py.
- [x] T004 [US1] Проверить health, включительную границу и загрузку >20 МиБ в tests/unit/test_app_remote.py.
## Phase 4: User Story 2
Цель: исключить передачу заведомо большого тела и ложную сетевую ошибку. Независимая проверка: старый health, превышение, 413, сетевой и локальный TypeError.
- [x] T005 [US2] Проверить точный multipart до POST и сохранить коды и журнал ошибок в extension/src/background.js.
- [x] T006 [US2] Добавить проверки лимита и диагностики в tests/js/test_extension_background.mjs.
## Phase 5: Polish
- [x] T007 Обновить docs/APP.md и docs/EXTENSION.md; собрать расширения scripts/build-extension.py.
- [x] T008 Выполнить проверки quickstart.md и сверку требований specs/006-large-image-upload/spec.md.

## Dependencies and Parallel Opportunities
T001 → T002 → T003 → T004; T005 → T006; затем T007 → T008. Изменения Python и JavaScript допускают независимое выполнение; внутри одного файла последовательно. Работа выполняется одним агентом.

## Implementation Strategy
Сначала серверный MVP US1, затем совместимый клиент US2. Автоматические проверки транспорта не заменяют реальный перевод и не дают статус accepted. Публикация и деплой отдельно.
