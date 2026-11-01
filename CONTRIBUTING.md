# Разработка

Пользовательская установка и запуск описаны в [README](README.md). Здесь — окружение разработчика, проверки, сборка и соглашения.

## Окружение

Python 3.10–3.13: CI гоняет unit-тесты на всех четырёх версиях. На 3.14 возможны проблемы с `torch`. Для окна на Windows нужен [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). Сборка Windows-приложения требует Flutter 3.47.7 или новее. Локальный `flutter` часто лежит в `%LOCALAPPDATA%\flutter\bin\flutter.bat`.

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
python scripts\setup_models.py
# GPU для локальной разработки, в релиз не попадает:
python scripts\setup_models.py --torch-cuda
```

Перед офлайн-обработкой из исходников: `python -m src.app --deploy all` (набор en→ru). В окне то же делает «Подготовить приложение».

`scripts\setup_models.py` скачивает детектор ogkalu в `models/` и LaMa-manga в `models/anime-manga-big-lama.pt`. Шрифт Heroika уже лежит в `src/resources/fonts/`; скрипт обновляет тот же файл. Модели в git не входят.

## Тесты

```powershell
python -m pytest tests/ -v -m "not slow and not ui"
python -m pytest tests/e2e/test_ui_smoke.py -v -m ui
python -m pytest tests/unit -m "not slow and not ui and not requires_llm and not requires_argos"
npm run test:js
```

Маркеры: `slow`, `ui`, `requires_argos`, `requires_llm`. JavaScript-тесты — `node --test` через `package.json`. Скрипты поставки: `tests/linux/test_deploy_scripts.sh`, `tests/windows/test_update_windows.ps1`. Сценарии расширения — `tests/e2e/test_extension_safe.py`.

Flutter-хост:

```powershell
cd apps\desktop
flutter analyze
flutter test
```

## Сборка Windows

Версия задаётся в `src/app/__init__.py` (`__version__`).

```powershell
.\scripts\build-windows.ps1
.\scripts\build-windows.ps1 -SkipPyInstaller
.\scripts\build-windows.ps1 -SkipFlutter
.\scripts\build-windows.ps1 -ServerZip
```

`-ServerZip` собирает Windows server zip через `scripts\package-server.ps1`. Архив Linux-сервера собирает `.github/workflows/release.yml`. `-SkipFlutter` не пересобирает хост.

Результат:

- `dist\ImageLocalizationTool\` — `desktop\` (Flutter-хост), `sidecar\` (Python), `web\`, `fonts\`; `models\` копируются, если они есть.
- Портативный ZIP: `dist\ImageLocalizationTool-<version>-windows-x64-portable.zip`.

Windows поставляется только портативным ZIP. `setup.exe` не собирается.

Проверка каталога сборки: `python scripts\smoke_dist.py`.

База лёгкого релиза не включает torch и Argos (`requirements-release.txt`). Модели и компоненты докачиваются при первом запуске.

```powershell
python -m venv venv-release
.\venv-release\Scripts\python.exe -m pip install -r requirements-release.txt pyinstaller
.\scripts\build-windows.ps1 -SkipModels -BuildPython venv-release\Scripts\python.exe
```

Для Windows NVIDIA программа выбирает компонент по драйверу: 580+ → `torch-cu130` (~1.93 ГБ), 570–579 → `torch-cu128` (~2.5 ГБ), иначе CPU (~125 МБ). Офлайн-перевод — en↔ru. Каждый файл сверяется по SHA-256. Без окна: `--deploy all` готовит набор en→ru, `--deploy cuda` ставит рекомендованный CUDA-компонент.

Обычный выпуск не подбирает зависимости заново. Перед `scripts\release.ps1 -Prepare` нужен чистый рабочий каталог и файл `docs\RELEASE_NOTES_<version>.md`. Команда гоняет тесты, собирает Windows и полный CPU ZIP, собирает расширения, затем на том же коммите запускает Linux CI (`release.yml`) и Docker CI (`docker.yml`) и кладёт проверенный комплект в draft. `scripts\release.ps1 -Publish -SmokePassed` публикует те же файлы. Обновление зависимостей — `scripts\build-runtime-locks.ps1 -UpdateCatalog`. Каталог рантайма собирает `scripts\build-runtime-manifest.py`, stdlib сайдкара — `scripts\build-stdlib-zip.py`, гейт адресов — `scripts\check_release.py`.

Полный CPU ZIP поверх актуального `dist`:

```powershell
.\scripts\package-portable.ps1 -Python venv-release/Scripts/python.exe -FullCpu
```

Docker и правила выпуска: [docs/DISTRIBUTIONS.md](docs/DISTRIBUTIONS.md).

## Деплой

```powershell
.\scripts\deploy-windows.ps1              # dist -> папка приложения, без models
.\scripts\deploy-windows.ps1 -Build
.\scripts\deploy-windows.ps1 -IncludeModels
.\scripts\deploy-lan.ps1                  # исходники на CT113, перезапуск ilt.service
.\scripts\deploy-lan.ps1 -DryRun
.\scripts\deploy-lan.ps1 -Hosts 192.168.88.41 -IncludeTests
.\scripts\deploy-extension.ps1            # dist/chromium -> папка расширения
```

Headless в LAN: `python -m src.app --headless --remote`, порт 8765 только в частной сети. Протокол без шифрования.

Linux-служба: [docs/LINUX_SERVER.md](docs/LINUX_SERVER.md). Обновление лёгкого Windows ZIP: [docs/WINDOWS_UPDATE.md](docs/WINDOWS_UPDATE.md).

## CI

- `.github/workflows/ci.yml` на push и pull request в `main`: pytest на Ubuntu (Python 3.10–3.13), `npm run test:js` (Node 22), `flutter analyze` и `flutter test` на Windows, job `e2e-browser` с `ILT_REQUIRE_BROWSER=1`. Flutter в CI — канал `stable`; локальный кандидат — 3.47.7 (`apps/desktop/README.md`).
- `.github/workflows/release.yml` по тегу `v*` собирает Linux server tar.gz.
- `.github/workflows/docker.yml` на каждый push в `main` публикует `edge-cpu-full` после реальной обработки.

## Спецификации

База — [specs/001-current-state/spec.md](specs/001-current-state/spec.md). Новая фича идёт через Spec Kit: `/speckit-specify`, затем `/speckit-plan`, `/speckit-tasks`, `/speckit-implement` и `/speckit-converge`. Нумерация продолжается с 002. Спецификация описывает изменение относительно базы. Принципы — `.specify/memory/constitution.md`. Старые спецификации лежат в `legacy/specs/` (папка в git не входит) и остаются в истории до коммита `c02fe23`.

## Соглашения

- Минимальный diff.
- Новый движок — новый файл в `src/components/`.
- Новые настройки — поля `Config` с дефолтами.
- Комментарии и docstring на русском.
- Не коммитить `models/`, `config.json`, `data/`, `test-img/`, `output/`, логи и папку `legacy/`.
