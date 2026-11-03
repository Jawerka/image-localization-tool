# Tasks: Кэш исходника

## Phase 1: Setup
- [x] T001 Создать спецификацию и план в specs/007-cached-image-source/.
## Phase 2: Foundational
- [x] T002 Проверить существующий suppliedBlob и границы разрешений в extension/src/background.js.
## Phase 3: User Story 1
Цель: получить сохранённый оригинал; независимая проверка — отключённый источник после прогрева.
- [x] T003 [US1] Добавить helper чтения страницы, таймаут, проверку источника и canvas в extension/src/image-source.js.
- [x] T004 [US1] Подключить helper в extension/src/inline-content.js, extension/manifest.chromium.json, extension/manifest.firefox.json и scripts/build-extension.py.
- [x] T005 [US1] Проверить кэш, пиксели и смену src в tests/js/test_extension_image_source.mjs и tests/e2e/test_extension_cached_source.py.
## Phase 4: User Story 2
Цель: сохранить запасное скачивание; независимая проверка — защищённый canvas и сетевой отказ.
- [x] T006 [US2] Разрешить кэш background и сохранить причины отказов в extension/src/background.js.
- [x] T007 [US2] Проверить фолбэки и поставку helper в tests/js/test_extension_background.mjs и tests/unit/test_extension_build.py.
## Phase 5: Polish
- [x] T008 Обновить docs/EXTENSION.md, выполнить quickstart.md и сверить требования specs/007-cached-image-source/spec.md.
- [x] T009 Собрать и обновить установленное расширение через scripts/deploy-extension.ps1; записать ограничения в specs/007-cached-image-source/validation.md.

## Dependencies and Strategy
T001→T002→T003→T004→T005; T006→T007; затем T008→T009. T003 и T006 затрагивают разные файлы, допускают независимую работу; выполняются одним агентом. Сначала доступные байты страницы, затем надёжный запасной путь. Старый коммит 006 сохраняется, публикация PR/merge не выполняется без разрешения.
