# Implementation Plan: Runtime Wheelset (schema 2)

**Branch**: `032-runtime-wheelset` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/032-runtime-wheelset/spec.md`

## Summary

Рантайм-паки остаются в `<install_root>/runtime/<id>/site-packages`, но наполняются не `.7z`-архивами из venv,
а официальными pip-колёсами: манифест schema 2 несёт `files[]` (url/sha256/size на каждый файл), генератор локов
резолвит пины через `pip install --dry-run --report` и скачивает колёса `pip download --no-deps --report`
(CI не ставит torch в venv), лок-файлы версионируются в репозитории в стиле A1111 (`locks/`). Клиент
`runtime.py` качает файлы по одному, сверяет sha256 каждого, распаковывает колёса пофайлово с zip-slip-защитой
и правилом конфликтов и ставит в существующую раскладку. Гейт релиза (Tier 1 HEAD + Tier 2 `import torch`
с `deep.json`), сквозной локальный E2E-скрипт, честные размеры в UI и доках. `.7z`-скрипты — deprecated.

## Technical Context

**Language/Version**: Python 3.10 (релиз 1.0.1, PyInstaller), PowerShell 5.1, Dart/Flutter stable

**Primary Dependencies**: stdlib (`urllib`, `zipfile`, `hashlib`, `json`, `concurrent.futures`); py7zr — только
archive-ветка; pip в венвах сборки: `--dry-run`, `--report`, `--no-deps`, `--only-binary`, `--index-url/--extra-index-url`

**Storage**: `<install_root>/runtime/<id>/{site-packages,pack.json}`; `dist/locks/` (артефакты сборки,
не коммитятся); `locks/py310-<os>.lock` (в репозитории); `build/deep.json` (кэш гейта)

**Testing**: pytest (фикстуры `.whl` через zipfile, генератор на фикстуре report.json, конфликты, манифест),
`flutter test` + `flutter analyze`, `scripts/e2e-runtime-local.ps1`

**Target Platform**: Windows x64 (основной), Linux x64 (сервер, CI)

**Constraints**: без `extractall`; минимальный diff; русские комментарии; контракты `/api/*`, `--deploy`,
portable не меняются; колёса не хостятся на GitHub; archive-ветка (schema 1) читается

**Scale/Scope**: `runtime.py` (+250 строк), 3 новых скрипта (locks, gate, e2e), правки 4 релизных скриптов,
Flutter ~4 файла, тесты; argos-пак: `argostranslate==1.11.0` из PyPI (подтверждено), torch 2.11.0 (cpu/cu128)

## Constitution Check

- Пайплайн v2 не тронут — PASS (меняется только доставка рантайма)
- Минимальный diff — PASS (новые скрипты — новые файлы; `.7z`-скрипты не удаляются, помечаются deprecated)
- Русский язык — PASS
- Локальные данные не коммитить — PASS (`locks/` — текстовые пины, не данные; паки/колёса вне git)
- Заявленное качество — PASS (не меняется)
- Совместимость — PASS (`/api/*`, `--deploy`, portable, LAN, окно сохраняются; schema 1 читается)

## Изменения

### 1. `src/app/runtime.py` — клиент колёс

- `WheelFile` (frozen dataclass): `name`, `url`, `sha256`, `size_bytes`; `Pack` + `format` (`wheels`/`archive`),
  `files: tuple[WheelFile, ...]`, `source` (host-метка: `PyPI`/`PyTorch CDN`/…).
- `_pack_from_dict`: читает schema 1 и 2; запись wheels валидна при непустых `files`, sha256 (64 hex) и
  размерах > 0; невалидная запись пропускается с логом.
- `download_and_install`: ветвление по `pack.format`:
  - `_download_files`: файлы по одному в `runtime/<id>.part/` (`.part` на файл), sha256 каждого до приёмки,
    общий прогресс (`done`/`total` = сумма), retry на обрыв, удаление `.part` при сбое; HTTPError — сразу ошибка.
  - `_extract_wheels`: zipfile, порядок — сортировка по имени колеса; для каждого entry — zip-slip-проверка
    (как в 7z-ветке), пропуск каталогов, `.data/`; конфликт: одинаковое содержимое — skip, разное — ошибка;
    запись в `<id>.tmp/site-packages`.
  - `_extract_pack` (py7zr) — без изменений, только archive-ветка.
- `_write_marker`: + `files` (name → sha256) и `source`; `installed_at`, `version` как раньше.
- `status()`: + `source`, `format` в записи пака (UI показывает источник).
- Активация, `Manager`, SSE — без изменений.

### 2. Генератор локов — `scripts/build_runtime_locks.py` + `scripts/build-runtime-locks.ps1` (новые)

- py: `--pack torch-cpu|torch-cu128|argos --os win|linux --python 310 --out dist/locks [--url-base …] [--hosted-wheel <файл>]`.
- Резолв без установки: `pip install --dry-run --ignore-installed --report resolve.json <спека>` с индексами
  (`torch`: `--index-url https://download.pytorch.org/whl/{cpu,cu128}` + `--extra-index-url https://pypi.org/simple`;
  `argos`: PyPI зависимости); из report — пины `name==version` (сортировка), url/sha256 колёс.
- Скачивание: `pip download --only-binary=:all: --no-deps -d <stage> <пины>` (те же индексы); sha256 каждого файла
  сверяется с отчётом, если индекс отдал хэш.
- `argostranslate`: PyPI-релиз жёстко требует stanza→torch, поэтому колесо собирается из официального git-пина
  `17ed1a9b…` (`pip wheel --no-deps`, 41 КБ, stanza optional) и публикуется ассетом релиза
  (`--hosted-wheel` — готовое колесо для CI); URL — `{url-base}/v{ver}/<имя>`.
- Выход: `dist/locks/<id>-<os>.json` (запись packs.json: `format:"wheels"`, `files[]`, `size_bytes` = сумма,
  `version` верхнего пакета, `driver_min` для cu128); merge в `dist/locks/packs.json`.
- Пин-файл: `locks/py310-<id>-<os>.lock` — полный freeze (name==version по алфавиту) для коммита в репо.
- ps1: Windows-обёртка: выбор python (venv/venv-release), прогон cpu/cu128/argos (для argos — сборка колеса).

### 3. `scripts/build-runtime-manifest.py` — schema 2 + валидация

- `build_manifest`: понимает записи wheels (URL файлов уже абсолютные — не переписываются) и archive
  (URL = `url_base/v{ver}/{file}`); `schema: 2`.
- `validate_manifest(manifest) -> list[str]` (общая с гейтом и тестами): wheels — `files[]` непуст, sha256
  64 hex, размеры > 0, `size_bytes` = сумма; archive — sha256 есть.
- Merge по `(id, os)` сохраняется; `--no-bundled` сохраняется.

### 4. Гейт — `scripts/check_release.py` (новый)

- `--manifest <path> --assets <dir> --deep --cache build/deep.json --skip-remote`.
- Tier 1: `validate_manifest` + HEAD каждого `files[].url` (и archive URL) в потоке (`ThreadPoolExecutor`),
  PyPI CDN и PyTorch CDN: код 200 и `Content-Length` == `size_bytes` файла (если заголовок есть).
- Tier 2 (`--deep`): установка `torch-cpu` из манифеста во временный `ILT_INSTALL_ROOT` через `src.app.runtime`
  + `import torch` в subprocess; результат кэшируется в `deep.json` по sha256(setup, portable, server, manifest)
  (из `--assets`, отсутствующие артефакты — пропускаются в ключе); повторный прогон с тем же ключом — skip.
- Exit 0/1; таблица результатов в stdout.

### 5. Пайплайн

- `.github/workflows/release.yml`: убрать venv+`.7z`-шаги; скачать ассет `argostranslate-*.whl` из draft
  (ожидание с ретраями, т.к. CI стартует по тегу); `python scripts/build_runtime_locks.py` для
  `torch-cpu` (linux) и `argos` (linux, `--hosted-wheel`); проверка воспроизводимости — `locks/py310-<id>-linux.lock`
  == закоммиченному (нет файла — warning + артефакт для бутстрапа); `packs-linux.json` = `dist/locks/packs.json`;
  `SHA256SUMS-linux.txt` только по tar.gz; upload: tar.gz + `packs-linux.json` + `SHA256SUMS-linux.txt`.
- `scripts/publish-release.ps1`: Windows-фаза читает `dist/locks/packs.json` вместо `dist/packs/*.7z`;
  в ассеты входит собранное колесо `dist/locks/argostranslate-*.whl` (и его строка в `SHA256SUMS`);
  Final — как раньше (merge сводок, пересборка манифеста, `SHA256SUMS.txt` без `packs/*.7z`).
- `scripts/build-runtime-packs.ps1`, `scripts/build-runtime-pack.py`: шапка «DEPRECATED: legacy .7z-сборка
  (specs/032); используйте build-runtime-locks» — файлы остаются.

### 6. UI (Flutter)

- `src/app/runtime.status()`: `source` + `format` (Python, см. п.1).
- `apps/desktop/lib/src/model/runtime_pack.dart`: поля `source`, `format`.
- `first_run_screen.dart`, `settings_screen.dart`: подпись `размер · источник · ~время` (ETA ≈ `sizeBytes / 10 МБ/с`,
  округление до минут); прогресс уже общий.
- `apps/desktop/test/runtime_wizard_test.dart` + `secondary_state_test.dart`: обновить/добавить ожидания.

### 7. Документация и версия

- `src/app/__init__.py`: `__version__ = "1.0.1"`.
- `docs/APP.md`: раздел «Компоненты: откуда и сколько» (таблица CPU ≈ 114 МБ, cu128 ≈ 2.56 ГБ, argos ≈ 40–80 МБ;
  PyPI/PyTorch CDN; интернет; прокси) + troubleshooting («загрузка не пошла»: повтор, лог, своё зеркало
  `ILT_RUNTIME_MANIFEST_URL` с примером).
- `README.md`: блок «при первом запуске докачиваются компоненты по выбору железа».
- `docs/RELEASE_NOTES_1.0.1.md`: матрица компонентов с честными размерами, источник, порядок зеркала.

### 8. E2E — `scripts/e2e-runtime-local.ps1` (новый)

- Прогон: pytest (runtime/manifest/generator) → win-локи (cpu+argos; `-Full` — cu128) → манифест с local
  url-base не нужен (URL CDN), встроенная копия не трогается (`--no-bundled`) → dev-E2E: `ILT_INSTALL_ROOT=build/e2e/root`,
  `python -m src.app --deploy cpu` и `--deploy argos`, повтор (идемпотентность), sha-подмена (ошибка+чистота) →
  frozen: `build-windows.ps1 -SkipModels` (если `-SkipBuild` нет), `package-portable.ps1`, распаковка в
  `build/e2e/portable`, `--deploy cpu` замороженным exe, `GET /api/runtime` (`torch_ready=true`) →
  `publish-release.ps1 -DryRun` + `check-release.py --deep`.
- Флаги: `-SkipBuild`, `-Full`, `-KeepStages`; любой сбой → non-zero.

## Тесты

- `tests/unit/test_runtime.py` (расширение): helper микро-колеса (zipfile: `pkg/__init__.py`, `dist-info/METADATA`,
  `RECORD`, `.data/scripts/x`); установка wheels-пака с `file://` URL; sha mismatch → ошибка без мусора;
  конфликт (равное — skip, разное — ошибка); `.data/scripts` не материализуется; `RECORD` на месте; schema 2
  parse (валидная/битая запись); archive-регрессия (существующие тесты).
- `tests/unit/test_runtime_locks.py` (новый): парсинг fixture report.json → пины и `files[]`; merge сводок;
  имя/сумма `size_bytes`.
- `tests/unit/test_manifest_schema2.py` (новый): `build_manifest`/`validate_manifest` — schema 2, ошибки
  (сумма, sha, пустой files, размер).
- Flutter: обновление `runtime_wizard_test.dart`, `secondary_state_test.dart`.

## Project Structure

```text
specs/032-runtime-wheelset/{spec,plan,research,data-model,quickstart,tasks}.md
specs/032-runtime-wheelset/contracts/{manifest-schema2.md,runtime-wheelset-api.md}

locks/py310-<id>-<os>.lock                            # в репозитории (пины A1111-стиля)
src/app/runtime.py, src/app/runtime_manifest.json, src/app/__init__.py
scripts/build-runtime-locks.ps1, scripts/build_runtime_locks.py, scripts/manifest_tools.py
scripts/build-runtime-manifest.py, scripts/check_release.py, scripts/e2e-runtime-local.ps1
scripts/build-runtime-packs.ps1, scripts/build-runtime-pack.py      # deprecated-шапки
scripts/publish-release.ps1, .github/workflows/release.yml

apps/desktop/lib/src/model/runtime_pack.dart
apps/desktop/lib/src/ui/screens/{first_run_screen.dart,settings_screen.dart}
apps/desktop/test/{runtime_wizard_test.dart,secondary_state_test.dart}

tests/unit/{test_runtime.py,test_runtime_locks.py,test_manifest_schema2.py}
docs/{APP.md,RELEASE_NOTES_1.0.1.md}, README.md
```

## Converge

- pytest полный; `flutter analyze` + `flutter test`.
- `scripts/e2e-runtime-local.ps1` зелёный (dev + frozen; `-Full` — cu128 на RTX).
- Installer smoke на машине разработчика: setup → мастер (размер/источник/время) → cu128 → LaMa на GPU.
- RC `v1.0.1-rc1`: CI (linux-локи, воспроизводимость, draft) → `publish-release.ps1 -Phase Final -DryRun`.
- Только после этого — финальный `v1.0.1`.

## Complexity Tracking

| Item | Why |
|------|-----|
| Колёса вместо `.7z` | Нет пересборки/трима venv; источник — официальные CDN с вечными hash-URL; SHA256SUMS без гигабайтов |
| `--dry-run --report` + `download --no-deps` | Резолв без установки torch в CI (главное ускорение), пины из отчёта pip — единственный источник URL/sha |
| `locks/` в репозитории | Стиль A1111: ревью пинов в PR, CI-проверка воспроизводимости, воспроизводимость релиза |
| Пофайловая распаковка | `extractall` не даёт ни zip-slip-контроля, ни правила конфликтов, ни детерминизма |
| Archive-ветка | Старые манифесты/пользовательские зеркала schema 1 продолжают работать |
