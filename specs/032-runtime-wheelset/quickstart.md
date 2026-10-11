# Quickstart: приёмка Runtime Wheelset (schema 2)

**Feature**: 032-runtime-wheelset | Контракты: [manifest-schema2.md](./contracts/manifest-schema2.md),
[runtime-wheelset-api.md](./contracts/runtime-wheelset-api.md); модель данных: [data-model.md](./data-model.md)

## Предусловия

- Windows, `venv`/`venv-release` с pip 26 (флаги `--dry-run/--report` есть), интернет к PyPI и PyTorch CDN.
- Для полного прогона: Inno Setup 6.1+, Flutter SDK в PATH, `gh` авторизован (только для RC-фазы).
- NVIDIA-машина (RTX) — для GPU-smoke (`-Full`).

## 1. Быстрые проверки (без сети)

```powershell
.\venv\Scripts\python.exe -m pytest tests\unit\test_runtime.py tests\unit\test_runtime_locks.py tests\unit\test_manifest_schema2.py -q
```

Ожидание: зелёные тесты колёс/генератора/манифеста (фикстуры `.whl` и `report.json` — офлайн).

## 2. Сквозной локальный прогон (главный гейт)

```powershell
.\scripts\e2e-runtime-local.ps1             # всё: pytest → локи win → dev-deploy → frozen → dry-run → гейт
.\scripts\e2e-runtime-local.ps1 -SkipBuild  # только то, что не требует пересборки базы
.\scripts\e2e-runtime-local.ps1 -Full       # + cu128 (≈2.5 ГБ, нужен NVIDIA)
.\scripts\e2e-runtime-local.ps1 -KeepStages # не чистить build\e2e для разбора
```

Шаги и ожидания:

1. pytest (см. §1).
2. `build-runtime-locks` (win: cpu, argos; `-Full` — cu128) → `dist/locks/*.json`, `locks/py310-win.lock`.
3. `build-runtime-manifest.py --no-bundled` → schema 2; валидация полноты зелёная.
4. dev-`--deploy cpu` и `--deploy argos` в `build\e2e\root` → импорт `torch`/`argostranslate` из
   `runtime\<id>\site-packages`; повторный `--deploy` → «уже установлено»; подмена байта в `.part` →
   ошибка и чистый каталог.
5. `build-windows.ps1 -SkipModels` → `package-portable.ps1` → распаковка portable в `build\e2e\portable` →
   `--deploy cpu` замороженным exe → `GET /api/runtime` c `torch_ready=true`.
6. `publish-release.ps1 -DryRun` → ассеты без `.7z`, `SHA256SUMS-windows.txt` без `packs/*.7z`.
7. `check-release.py --deep` → Tier 1 (структура + HEAD CDN) и Tier 2 (install+import, `deep.json`).

Любой сбой — non-zero; релиз не собирается до зелёного прогона.

## 3. Ручные проверки после E2E

- **Installer smoke**: `installer\` сборка → `dist\...setup.exe` → мастер: подписи компонентов с честным
  размером/источником/временем → на NVIDIA поставить `cu128` → LaMa на GPU (`device=auto`).
- **Зеркало (из доков)**: поднять `python -m http.server` над `dist\` с манифестом+фикстурой колёс, задать
  `ILT_RUNTIME_MANIFEST_URL=http://127.0.0.1:8000/…json`, установить пак — сценарий README/APP.md работает.
- **Flutter**: `flutter analyze` и `flutter test` в `apps\desktop` — зелёные.

## 4. RC-репетиция (GitHub)

```powershell
git tag -f v1.0.1-rc1; git push -f origin v1.0.1-rc1     # запускает release.yml
# после CI: linux-локи, tar.gz, packs-linux.json в draft
.\scripts\publish-release.ps1 -Phase Final -DryRun        # merge сводок без публикации
```

Ожидание: CI зелёный (включая проверку воспроизводимости linux-лока), Final dry-run собирает полный
манифест schema 2 и `SHA256SUMS.txt` без `packs/*.7z`. При успехе — финальный `v1.0.1` по плану публикации.

## Трассировка требований

| Требование | Проверка |
|------------|----------|
| FR-001/FR-005/FR-006/FR-007 | §1, §2.4 (тесты + dev-deploy) |
| FR-002/FR-003/FR-004 | §2.2, CI-шаг воспроизводимости (§4) |
| FR-008/FR-009 | §2.4–2.5 (маркер, идемпотентность, активация) |
| FR-010 | §2.6, §4 |
| FR-011 | §2.7 |
| FR-012 | §3 (UI), `test\runtime_wizard_test.dart` |
| FR-013 | §3 (зеркало) + ревью `docs/APP.md`, README |
| FR-016 | §2 целиком |
| FR-017 | §3 installer smoke, §4 RC |
