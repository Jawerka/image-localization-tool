# Feature Specification: Release Packaging — сборка и публикация 1.0.0

**Feature Branch**: `031-release-packaging`

**Created**: 2026-10-11

**Status**: Draft

**Input**: План «универсальный релиз 1.0.0 с развёртыванием (ComfyUI-подход)»: база (Flutter-хост + sidecar без torch/Argos + web + fonts), паки отдельными `.7z`-ассетами, portable/server zip, Linux-бинарник в CI, расширения chromium/firefox, `SHA256SUMS.txt`, `ilt-runtime-manifest-1.0.0.json`. Инсталлятор Inno с `lzma2/ultra64`. Тег `v1.0.0`: старый черновик и remote-тег удаляются, финальный тег ставится на итоговый коммит.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Сборка универсальной базы (Priority: P1)

Разработчик на Windows запускает `scripts\build-windows.ps1` — собираются Flutter-хост, sidecar без torch (`requirements-release.txt`, excludes), `stdlib.zip`, `web`, `fonts`; smoke проверяет раскладку и отсутствие torch; Inno собирает setup с `lzma2/ultra64`. Размер setup ~150–200 МБ.

**Why this priority**: база — то, что скачивает каждый пользователь; без неё нет релиза.

**Independent Test**: собрать базу, проверить `smoke_dist.py` (нет `_internal/torch`, есть `stdlib.zip`), размер setup ≤ 220 МБ, sidecar стартует.

**Acceptance Scenarios**:

1. **Given** чистый `venv-release` (без torch), **When** `build-windows.ps1 -SkipModels`, **Then** сборка успешна, setup создан.
2. **Given** собранный dist, **When** `smoke_dist.py`, **Then** нет `torch/lib`-требований, есть `stdlib.zip`, шрифты и `web` на месте.
3. **Given** Inno 6.1+, **When** сборка, **Then** `Compression=lzma2/ultra64`, setup с версией 1.0.0.

---

### User Story 2 - Сборка паков `.7z` (Priority: P1)

`scripts\build-runtime-packs.ps1` собирает CPU/CUDA/Argos паки: чистые venv, `pip install` с пинами, вырезка лишнего (заголовки, `.lib`, тесты, кэш), `.7z` через py7zr, sha256 и размер в JSON-сводку для манифеста. Linux-паки — в CI тем же скриптом.

**Independent Test**: собрать `torch-cpu` (win), распаковать в `runtime/`, sidecar подхватывает, LaMa работает (spike).

**Acceptance Scenarios**:

1. **Given** пак собран, **When** `runtime.download_and_install` из локального файла, **Then** sha сходится, распаковка, активация.
2. **Given** сводка паков, **When** генерация манифеста, **Then** `ilt-runtime-manifest-1.0.0.json` содержит url/sha256/size всех паков.
3. **Given** пак для другой платформы, **Then** он не предлагается в UI.

---

### User Story 3 - Portable и серверные ассеты (Priority: P2)

`...-windows-x64-portable.zip`: `desktop/`, `sidecar/`, `web/`, `fonts/`, пустые `data/`, `models/`, `runtime/`. `...-server-win64.zip`: sidecar + `web` + `fonts` + `deploy.cmd` (`--headless --remote`, затем `--deploy models`). `...-server-linux-x64.tar.gz`: бинарник из CI + `deploy.sh`.

**Independent Test**: распаковать portable в чистый каталог — данные пишутся внутрь; запустить серверный deploy.

**Acceptance Scenarios**:

1. **Given** portable zip, **When** первый запуск, **Then** `data/` и `models/` создаются/используются внутри каталога.
2. **Given** server-win64.zip, **When** `deploy.cmd`, **Then** скачиваются модели и запускается headless-сервер.

---

### User Story 4 - Расширения браузера (Priority: P2)

`ilt-extension-chromium-1.0.0.zip`, `ilt-extension-firefox-1.0.0.zip` + инструкция по распаковке/загрузке.

**Independent Test**: `scripts/build-extension.py` (или правка) собирает оба zip; содержимое совпадает с `extension/`.

---

### User Story 5 - Публикация релиза (Priority: P1)

Финальный коммит на `main`, удаление черновика `v1.0.0` и remote-тега, новый тег `v1.0.0` на итоговый коммит, сборка Windows-ассетов, CI Linux, загрузка всех ассетов, `SHA256SUMS.txt` + манифест с хешами, notes с матрицей «что выбрать», publish, smoke с задеплоенного exe.

**Why this priority**: без публикации фича не доходит до пользователя.

**Independent Test**: `gh release view v1.0.0 --json assets` содержит все ассеты; суммы сходятся; smoke-прогон с установщика.

**Acceptance Scenarios**:

1. **Given** устаревший draft `v1.0.0`, **When** публикация, **Then** старый draft и тег удалены, новый тег указывает на итоговый коммит.
2. **Given** CI отработал, **When** проверка ассетов, **Then** есть linux-архив и `torch-cpu-linux`/`argos-linux` паки.
3. **Given** релиз опубликован, **When** установка setup.exe на чистой машине, **Then** мастер предлагает компоненты, установка cu128 на NVIDIA даёт CUDA.

---

### Edge Cases

- Нет Inno 6.1+ или Flutter в PATH — понятная ошибка сборки.
- `gh` не авторизован — publish-скрипт останавливается до удаления тега.
- CI упал — Windows-ассеты уже собраны, публикация повторяема (идемпотентный upload `--clobber`).
- Кэш pip повреждён — скрипт продолжает с `--no-cache-dir` fallback.
- Тег уже существует локально/удалённо — скрипт удаляет и создаёт заново (по плану).

## Requirements *(mandatory)*

- **FR-001**: MUST существовать `requirements-release.txt` — без torch, torchvision, argostranslate, spacy, ctranslate2, stanza, playwright, pytest, black; с cv2, Pillow, fonttools, numpy, rapidocr, onnxruntime, rarfile, py7zr, requests, pyphen, keyring.
- **FR-002**: `ImageLocalizationTool.spec` MUST исключать torch/Argos-стек и dev-пакеты; MUST добавлять `stdlib.zip` в `_internal`; runtime hook torch удаляется; smoke MUST валидировать базу без torch.
- **FR-003**: `scripts/build-stdlib-zip.py` MUST собирать `stdlib.zip` из Lib сборки Python (без `test/tkinter/idlelib/lib2to3/ensurepip/site-packages`), размер ~3 МБ; `build-windows.ps1` вызывает его и кладёт zip в dist.
- **FR-004**: `scripts/build-runtime-packs.ps1` + `scripts/build-runtime-pack.py` MUST собирать паки: `torch-cpu` (win/linux), `torch-cu128` (win), `argos` (win/linux); имена `ilt-runtime-<kind>-<variant>-<os>-x64-py310.7z`; trim заголовков/тестов/кэша; сводка `dist/packs/packs.json` с sha256 и size.
- **FR-005**: `scripts/package-portable.ps1` MUST собирать portable zip по раскладке из US3 (пустые `data/`, `models/`, `runtime/` создаются); `scripts/package-server.ps1` — server-win64.zip с `deploy.cmd`; Linux tar.gz собирает CI (тот же `deploy.sh`).
- **FR-006**: `scripts/build-extension.py` MUST собирать `ilt-extension-chromium-<ver>.zip` и `ilt-extension-firefox-<ver>.zip`; Firefox-манифест (`manifest.firefox.json` или MV2-вариант) — если требуется существующим расширением (проверяется в задаче).
- **FR-007**: `installer/ImageLocalizationTool.iss` MUST использовать `Compression=lzma2/ultra64`; версия и имя setup — из `AppVersion`.
- **FR-008**: CI workflow `.github/workflows/release.yml` MUST по тегу `v*` и `workflow_dispatch` собирать на ubuntu: sidecar (PyInstaller one-dir), `torch-cpu-linux`, `argos-linux` паки, `...-server-linux-x64.tar.gz`; заливать в релиз тега (`permissions: contents: write`, `gh release upload --clobber`).
- **FR-009**: `scripts/publish-release.ps1` MUST: проверять `gh auth`, удалять старый релиз/тег (по плану), формировать `SHA256SUMS.txt` по локальным и Linux-ассетам (через API релиза), генерировать `ilt-runtime-manifest-1.0.0.json` с хешами и URL, загружать ассеты, создавать draft, применять notes, публиковать.
- **FR-010**: MUST существовать `docs/RELEASE_NOTES_1.0.0.md` с матрицей «что выбрать» (база/cpu/cu128/argos/portable/server), требованиями (драйвер ≥ 570, Windows 10/11 x64), инструкцией расширения и SHA-256.
- **FR-011**: Smoke MUST проверять: base без torch, наличие `stdlib.zip`, размер setup ≤ 220 МБ, версии ассетов 1.0.0; CUDA smoke — LaMa на GPU; `scripts/smoke_dist.py` обновляется.
- **FR-012**: Публикация идемпотентна и повторяема: `--clobber` на загрузке, повторный запуск не дублирует ассеты; тег переставляется только скриптом публикации.

## Key Entities

- **Ассет релиза**: имя, назначение, платформа, размер, sha256.
- **Сводка паков** (`dist/packs/packs.json`): записи манифеста без url (url подставляет publish).
- **Манифест рантайма**: см. спеку 030, `data-model.md`.

## Success Criteria *(mandatory)*

- **SC-001**: `setup.exe` universal ≤ 220 МБ; portable zip и server zip собираются из одного dist.
- **SC-002**: Все 7+ ассетов из плана опубликованы; `SHA256SUMS.txt` сходится с локальными файлами; манифест ссылается на правильные URL.
- **SC-003**: CI Linux собирает и заливает ассеты по тегу без ручных шагов.
- **SC-004**: Smoke с задеплоенного setup.exe: мастер 1.0.0, 0 orphan-процессов, компоненты устанавливаются.

## Assumptions

- GitHub-репозиторий `Jawerka/image-localization-tool`; release URL формируется из `__version__` и тега `v<version>`.
- Windows-ассеты собираются локально (Inno), Linux — в CI.
- pip-индексы: PyPI + `download.pytorch.org/whl/cpu` и `/cu128`.
- Argos-пак ставится из git-ссылки PyPI (`argostranslate @ git+…`) — как в текущем `requirements.txt` (пакет собирается скриптом, не инсталлятором).
- Публикация выполняется с машины разработчика с авторизованным `gh`.
