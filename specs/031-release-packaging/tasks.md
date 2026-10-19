# Tasks: 031-release-packaging

## Spec & plan

- [x] T001 `spec.md` (US1–US5, FR-001…FR-012)
- [x] T002 `plan.md`

## База

- [x] T003 `requirements-release.txt` (без torch/Argos/dev)
- [x] T004 `ImageLocalizationTool.spec`: excludes, `stdlib.zip` + `runtime_manifest.json` в datas, убран torch runtime hook
- [x] T005 `scripts/build-stdlib-zip.py` + вызов из `build-windows.ps1`; `smoke_dist.py --expect-no-torch`
- [x] T006 `installer/ImageLocalizationTool.iss`: `lzma2/ultra64`

## Паки

- [x] T007 `scripts/build-runtime-pack.py` (trim, py7zr LZMA2, sha256, `packs.json`)
- [x] T008 `scripts/build-runtime-packs.ps1` (чистые venv, cpu/cu128/argos win)
- [x] T009 Linux-паки в CI (cpu, argos) тем же Python-скриптом

## Ассеты

- [x] T010 `scripts/package-portable.ps1` (zip с `data/ models/ runtime/`) — 97 МБ
- [x] T011 `scripts/package-server.ps1` (win zip + `deploy.cmd` с `chcp 65001`) + `scripts/deploy-server.sh` — 116 МБ
- [x] T012 `scripts/build-extension.py`: zip chromium/firefox (`dist/ilt-extension-*-1.0.0.zip`)
- [x] T013 `.github/workflows/release.yml` (тег/dispatch, Linux sidecar + паки + tar.gz + upload)
- [x] T014 `scripts/publish-release.ps1` (две фазы: Windows-ассеты → Final после CI; SHA256SUMS, манифест, notes, publish)
- [x] T015 `docs/RELEASE_NOTES_1.0.0.md` (матрица, требования, расширение)

## Tests

- [x] T016 `tests/unit/test_packaging.py`: excludes, requirements-release, stdlib.zip, манифест, workflow, pack-скрипты
- [x] T017 `smoke_dist --expect-no-torch` на собранной базе — OK

## Verify & Converge

- [x] T018 Сборка базы: setup **154.1 МБ** (≤ 220)
- [x] T019 Сборка CPU-пака win + установка в `runtime/` + frozen-сайдкар `torch_ready=true`
- [~] T020 CUDA-пак win собран; GPU-проверка LaMa на RTX 5060 (см. 030 T024) (superseded by 033/current release)
- [x] T021 Portable/server smoke: распаковка в чистый каталог; `--deploy cpu` кладёт пак внутрь каталога
- [x] T022 Полный pytest + flutter — зелёные

## Итог и отклонения

- Размеры лучше оценок: CPU-пак 61 МБ (было ~170), Argos 37 МБ (было ~100), portable 97 МБ, server 116 МБ, setup 154 МБ.
- CUDA-пак сжимается заметно (torch/lib DLL), итог фиксируется в манифесте релиза.
- CI-сборка Linux проверяется только на GitHub Actions (локально PyInstaller не кросс-компилирует).
