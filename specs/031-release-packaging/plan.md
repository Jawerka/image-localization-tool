# Implementation Plan: Release Packaging

**Branch**: `031-release-packaging` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/031-release-packaging/spec.md`

## Summary

База: `requirements-release.txt` без torch/Argos, excludes в spec, `stdlib.zip` в `_internal`,
smoke без требования `torch/lib`, Inno `lzma2/ultra64`. Паки: скрипты на py7zr (общий Python-модуль
+ PowerShell-обёртка), сводка с sha256. Ассеты: portable zip, server win zip, Linux tar.gz (CI),
расширения zip, `SHA256SUMS.txt`, манифест. Публикация — `scripts/publish-release.ps1` и CI
`.github/workflows/release.yml`.

## Technical Context

**Language/Version**: Python 3.10 (сборка), PowerShell 5.1, GitHub Actions (ubuntu-latest)
**Primary Dependencies**: py7zr, PyInstaller 6, Inno Setup 6.1+, Flutter stable, `gh` CLI
**Storage**: `dist/` (не коммитится)
**Testing**: обновлённый `scripts/smoke_dist.py`, `tests/unit/test_packaging.py` (статичные проверки),
ручные сборки
**Target Platform**: Windows x64, Linux x64
**Constraints**: версия — только `src/app/__init__.py`; имена ассетов фиксированы; локальные данные не коммитить
**Scale/Scope**: ~8 скриптов сборки/публикации, spec, iss, ci workflow, notes, smoke

## Constitution Check

- Pipeline v2 не тронут — PASS
- Минимальный diff — PASS (спека правится точечно: excludes + datas; скрипты — новые файлы)
- Комментарии на русском — PASS
- Локальные данные не коммитить — PASS (dist/, packs/, venv — вне git)
- Совместимость — PASS (существующие скрипты `build-windows.ps1`, `deploy-*.ps1` сохраняются,
  расширяются флагами)

## Изменения

### 1. База

- `requirements-release.txt` (новый) — база без torch/Argos/dev.
- `ImageLocalizationTool.spec`:
  - excludes: `torch`, `torchvision`, `torchgen`, `argostranslate`, `spacy`, `ctranslate2`, `stanza`,
    `sentencepiece`, `sacremoses`, `minisbd`, `sympy`, `networkx`, `jinja2`, `scipy`, `matplotlib`,
    `playwright`, `pytest`, `IPython`, `jupyter`, `sphinx`, `tkinter`;
  - `datas`: `stdlib.zip` → `_internal` (если файл есть; иначе предупреждение);
  - runtime hook `scripts/pyi_rth_torch_dlls.py` — убрать из `runtime_hooks`.
- `scripts/build-windows.ps1`: перед PyInstaller — генерация `stdlib.zip`
  (`scripts/build-stdlib-zip.py` в `dist/`), передача пути в spec через env/файл; после сборки —
  проверка размера; portable/server zip по флагам `-Portable`, `-ServerZip` (или отдельные скрипты).
- `scripts/smoke_dist.py`: base-режим без `torch/lib`; обязательный `stdlib.zip` в `_internal`;
  `--expect-no-torch` флаг для релизной сборки.

### 2. Паки

- `scripts/build-runtime-pack.py` (новый, кросс-платформенный):
  `--kind torch|argos --variant cpu|cu128 --platform win|linux --venv <path> --out <dir>`,
  копирует site-packages из venv, trim (`__pycache__`, `*.lib`, `include/`, `test*`, `*.pdb`,
  dist-info оставить), упаковывает py7zr (LZMA2, solid), пишет запись в `packs.json` (sha256, size).
- `scripts/build-runtime-packs.ps1` (новый): создаёт чистые venv (`build/runtime-venvs/<...>`),
  `pip install torch==2.11.0+cpu|+cu128` / argostranslate+цепи, вызывает Python-скрипт,
  кладёт `.7z` в `dist/packs/`.
- Linux-сборка паков — в CI теми же скриптами (bash-шаги: venv + `build-runtime-pack.py`).

### 3. Ассеты

- `scripts/package-portable.ps1`: `dist/ImageLocalizationTool` → zip + пустые `data/ models/ runtime/`
  (внутри архива).
- `scripts/package-server.ps1`: sidecar + web + fonts + `deploy.cmd` (Win) → zip; для Linux скрипт
  CI собирает tar.gz и кладёт `deploy.sh`.
- `scripts/build-extension.py`: обзор текущего; добавить zip-упаковку chromium/firefox с версией;
  проверить наличие firefox-манифеста (если нет — добавить `extension/manifest.firefox.json`).
- `installer/ImageLocalizationTool.iss`: `Compression=lzma2/ultra64`.

### 4. CI

- `.github/workflows/release.yml`:
  - триггеры: `push: tags: v*`, `workflow_dispatch` (input `tag`);
  - job `linux`: setup-python 3.10, `pip install -r requirements-release.txt -r` build-зависимости
    (pyinstaller), pyinstaller по spec (base), `scripts/build-stdlib-zip.py`, Linux паки
    (cpu + argos), tar.gz + deploy.sh, `gh release upload <tag> … --clobber`.
  - `permissions: contents: write`.

### 5. Публикация

- `scripts/publish-release.ps1`:
  1. преflight: версия из `src/app/__init__.py`, `gh auth status`;
  2. удаление существующего релиза/тега `v<ver>` (план: старый черновик и remote-тег) — только с
     явным флагом `-ResetTag` для безопасности;
  3. сборка/проверка наличия локальных ассетов (setup, portable, server-win, packs, extensions);
  4. `SHA256SUMS.txt` (локальные + подождать/скачать список CI-ассетов);
  5. манифест с url/sha/size;
  6. `gh release create v<ver> --draft --title … --notes-file docs/RELEASE_NOTES_1.0.0.md`,
     upload всех ассетов `--clobber`;
  7. `gh release edit v<ver> --draft=false` (publish) по флагу `-Publish`.
- `docs/RELEASE_NOTES_1.0.0.md` — матрица выбора, требования, инструкция расширения.

### 6. Тесты

- `tests/unit/test_packaging.py`: парсинг spec (исключения torch), `requirements-release.txt` без
  torch/argos, генератор stdlib-списка, `packs.json` ↔ манифест (schema/поля), имена ассетов.
- Smoke: `scripts/smoke_dist.py` c новым base-режимом.

## Project Structure

```text
specs/031-release-packaging/{spec,plan,tasks}.md

requirements-release.txt
ImageLocalizationTool.spec
installer/ImageLocalizationTool.iss
scripts/{build-stdlib-zip.py,build-runtime-pack.py,build-runtime-packs.ps1,
  package-portable.ps1,package-server.ps1,publish-release.ps1,build-extension.py,smoke_dist.py,build-windows.ps1}
.github/workflows/release.yml
docs/RELEASE_NOTES_1.0.0.md
tests/unit/test_packaging.py
```

## Converge

- `build-windows.ps1` → dist + setup ≤ 220 МБ → smoke.
- `build-runtime-packs.ps1 -Variant cpu` → пак → install → LaMa (spike повторно).
- `package-portable.ps1` → распаковка в чистый каталог → запуск.
- Пробный `publish-release.ps1 -DryRun` (без gh) — генерация сумм и манифеста.
- Полный pytest + flutter.

## Complexity Tracking

| Item | Why |
|------|-----|
| Шаг «torture» сборки CUDA-пака локально | 2.7 ГБ wheel: скачивается один раз, кэшируется между сборками |
| `publish-release.ps1` с `-DryRun/-ResetTag` | публикация необратима; ручной контроль тега по плану |
| Linux-сборка только в CI | PyInstaller не кросс-компилирует |
