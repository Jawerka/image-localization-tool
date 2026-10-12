# Tasks: 032-runtime-wheelset

**Input**: design-документы `specs/032-runtime-wheelset/` (spec, plan, research, data-model, contracts, quickstart)

## Spec & план

- [x] T001 `spec.md` (US1–US5, FR-001…FR-017, Clarifications 2026-10-11), `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

## Клиент колёс (`src/app/runtime.py`) — US1

- [x] T002 `WheelFile`; `Pack` + `format`/`files`/`source`; `_pack_from_dict` читает schema 1+2, валидирует и пропускает битые записи
- [x] T003 `_download_files`: пофайлово `.part`, sha256 каждого, общий прогресс (сумма), retry, очистка при сбое
- [x] T004 `_extract_wheels`: zipfile, сортировка по имени, zip-slip, `.data/` skip, конфликты (равное — skip, разное — ошибка), `dist-info`/`RECORD` сохраняются
- [x] T005 маркер `pack.json` (+`files`, `source`, `format`); `status()` отдаёт `source`/`format`; archive-ветка без изменений
- [x] T006 `tests/unit/test_runtime.py`: микро-`.whl` helper (zipfile), install, sha mismatch, конфликты, `.data`/`RECORD`, schema 2 parse, archive-регрессия (25 тестов)

## Генератор локов и манифест — US2

- [x] T007 `scripts/build_runtime_locks.py`: resolve (`pip install --dry-run --report`) → download (`pip download --no-deps`) → `dist/locks/<id>-<os>.json`, merge `packs.json`, пин-файл; argos — сборка колеса из git-пина (`pip wheel`) + `--hosted-wheel`
- [x] T008 `scripts/build-runtime-locks.ps1`: win-драйвер (cpu/cu128/argos, выбор python)
- [x] T009 `locks/py310-<id>-win.lock` сгенерированы (cpu+cu128+argos; в рабочем дереве, коммит — с релизным пакетом)
- [x] T010 `scripts/manifest_tools.py` (`build_manifest`/`validate_manifest`) + `scripts/build-runtime-manifest.py`: schema 2
- [x] T011 `tests/unit/test_runtime_locks.py`, `tests/unit/test_manifest_schema2.py` (фикстуры report.json; ошибки валидации)

## Гейт — US1/US3 (инфраструктура релиза)

- [x] T012 `scripts/check_release.py`: Tier 1 — `validate_manifest` + HEAD всех URL (пул, 200 + Content-Length); draft-ассеты своего релиза — через GitHub API по токену
- [x] T013 Tier 2 `--deep`: установка `torch-cpu` + `import torch` в subprocess; кэш `deep.json` по sha256(setup, portable, server, manifest)
- [x] T014 `tests/unit/test_check_release.py`: структура, ключ кэша, HEAD-разбор (без сети); гейт подключён к `publish-release.ps1` (обе фазы)

## Пайплайн — US3/US4

- [x] T015 `.github/workflows/release.yml`: скачивает hosted-колесо argos из draft (ретраи); linux-локи без установки torch; проверка воспроизводимости `locks/py310-<id>-linux.lock` (бутстрап-артефакт); upload tar.gz + `packs-linux.json` + `SHA256SUMS-linux.txt` (без `packs/*.7z`)
- [x] T016 `scripts/publish-release.ps1`: Windows-фаза читает `dist/locks/packs.json`, грузит колесо argos (фильтр расширений по версии); ассеты и `SHA256SUMS` без `.7z`; Final merge; гейт после загрузок
- [x] T017 deprecated-шапки в `scripts/build-runtime-packs.ps1` и `scripts/build-runtime-pack.py` (ASCII)
- [x] T018 `locks/py310-<id>-linux.lock`: бутстрап из RC-прогона CI (bootstrap-артефакт), закоммичены `bfab938`; финальный прогон — строгая сверка

## UI и документация — US4/US5

- [x] T019 Flutter: `runtime_pack.dart` (`source`, `format`); подписи «размер · источник · ~время» в мастере и настройках; тесты обновлены (123 flutter-теста зелёные)
- [x] T020 `docs/APP.md`: «Компоненты: откуда и сколько» + «Загрузка не пошла»; `README.md`: первый запуск и сборка без torch
- [x] T021 `src/app/__init__.py` → `1.0.1`; `docs/RELEASE_NOTES_1.0.1.md` (матрица, честные размеры, источник)

## Сквозная приёмка — US1…US5

- [x] T022 `scripts/e2e-runtime-local.ps1`: pytest → win-локи → манифест → dev-deploy (cpu/argos, идемпотентность, битый sha) → frozen portable (`--deploy cpu`, импорт torch) → `publish-release.ps1 -DryRun` + `check_release.py --deep`; флаги `-SkipBuild`, `-Full`, `-KeepStages`
- [x] T023 pytest полный (477+ тестов) + `flutter analyze` + `flutter test` — зелёные
- [x] T024 Прогон `e2e-runtime-local.ps1` — ЗЕЛЁНЫЙ: dev+frozen установка, dry-run публикации (9 ассетов), Tier 1 HEAD 74 URL, Tier 2 `import torch ok: 2.11.0+cpu`
- [ ] T025 Installer smoke: GUI-мастер (размер/источник/время) — вручную; GPU-часть выполнена скриптом: cu128 установлен, `torch 2.11.0+cu128`, `cuda: True`, RTX 5060 Laptop
- [x] T026 RC `v1.0.1-rc1`: CI run 38178462902 зелёный (linux-локи, tar.gz, `packs-linux.json` в draft); linux-локи закоммичены; `publish-release.ps1 -Phase Final -DryRun -TagOverride v1.0.1-rc1` — merge ок (5 паков, sums 10 файлов)
- [ ] T027 Финальный `v1.0.1`: сборка/публикация (после T025–T026; по подтверждению)

## Зависимости

T007–T008 → T009–T018; T002–T005 → T006, T012–T014, T022; T010 → T011, T015–T016;
T019–T021 независимы; T023–T027 — после реализации, релиз по подтверждению.

## Смоук-фиксы (портативная сборка, 2026-10-12)

- [x] Удаление torch-пака: `remove()` при залоченных DLL переименовывает в `<id>.tmp`, `activate()` подчищает на старте; юнит-тест
- [x] Сервер: 500 логируется с путём запроса; guard от параллельных `models/download` одного kind (409)
- [x] UI: `errorText` в «Компонентах» (настройки+мастер) + подсказка про перезапуск; %-текст и мгновенный старт моделей; ключ API в мастере LLM (keyring)
- [x] `IltTextField`: контроллер вместо key-ремаунта (набор текста больше не теряет фокус)
- [x] Живая SSE-проба: `model.progress` идёт (0→55%→100%, total корректен) — «стоял бар» был UX-эффектом быстрых загрузок без процентов, бэкенд исправен
- [x] Пересборка: dist очищен (кроме `locks`), setup/portable/server 1.0.1 + расширения; e2e `-SkipBuild -KeepStages` зелёный (портатив torch 2.11.0+cpu, dry-run 7 ассетов, Tier 1 74 URL, Tier 2 import ok)

## Итог и отклонения

- **argos**: PyPI-релиз 1.11.0 жёстко требует stanza→torch (216 МБ с torch); взято официальное
  git-колесо по пину `17ed1a9b…` (stanza optional), публикуется одним ассетом релиза.
  Итог argos/win: 64 колеса, 88.7 МБ.
- **Размеры (win)**: torch-cpu 124.6 МБ (10 колёс), torch-cu128 2.76 ГБ (10 колёс), argos 88.7 МБ.
  UI/доки честно берут из манифеста; в доки занесено ~125 МБ / ~2.8 ГБ / ~90 МБ.
- **Хосты колёс**: parts.pythonhosted.org + download-r2.pytorch.org; Tier 1 HEAD подтвердил живость.
- **Починки по пути**: `ExtractToDirectory` чанк-конфликт в e2e (−KeepStages reuse); `$LASTEXITCODE`
  GUI-exe (Start-Process -Wait -PassThru); robocopy-утечка exit-кода (`exit 0` в упаковщиках);
  PS 5.1 BOM для кириллицы в e2e; ASCII-правило для релизных PS-скриптов.
- **Интервал манифеста**: встроенная копия сейчас = win-колёса + старые linux-плейсхолдеры;
  после RC пересобрать с linux-сводкой (release prep).
