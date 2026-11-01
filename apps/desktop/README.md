# ilt_desktop — Flutter-хост Image Localization Tool

Поставляемое приложение: в dist хост лежит в `desktop/`, сам
запускает замороженный сайдкар из `sidecar/` (`--api --parent-pid`), читает
handshake (`api.json` / stdout), ходит в локальный HTTP с cookie `ilt_session`
и подписывается на SSE `/api/events`. В исходниках сайдкар поднимается как
`python -m src.app --api`.

## SDK

- Pin: **Flutter ≥ 3.47.7** stable (для сборки — Visual Studio 2022
  с Desktop C++). `environment.sdk: ^3.12.0` — совместимый пол.

## Команды

Локальный SDK кандидата: **Flutter 3.47.7** stable (как pin ниже). CI берёт канал `stable`. На машине разработчика `flutter` может быть не в PATH; сборка и `scripts/release.ps1` вызывают `%LOCALAPPDATA%\flutter\bin\flutter.bat`.

Диагностика зависания (не снимать чужие lock SDK):

```powershell
$flutter = "$env:LOCALAPPDATA\flutter\bin\flutter.bat"
& $flutter --version
& $flutter analyze
& $flutter test
```

Прогон 2026-11-01: analyze без замечаний, 192 теста прошли. Логи: `data/flutter-analyze.log`, `data/flutter-test.log` (каталог data локальный).

```powershell
flutter pub get
flutter analyze
flutter test

# обычный запуск: хост сам поднимет python -m src.app --api
flutter run -d windows

# attach: подключиться к уже запущенному сайдкару (без spawn/kill)
flutter run -d windows --dart-define=ILT_ATTACH=1
```

## Переменные окружения (dev)

| Переменная | Назначение |
|------------|------------|
| `ILT_REPO_ROOT` | корень репозитория для `python -m src.app` (иначе ищется вверх по каталогам) |
| `ILT_PYTHON` | путь к python (например, `venv\Scripts\python.exe`) |
| `ILT_SIDECAR_EXE` | готовый exe сайдкара вместо `python -m src.app` |
| `ILT_DATA_DIR` | каталог данных (где `api.json`, `instance.json`) |
| `ILT_API_JSON` | полный путь к `api.json` для attach |

Корень данных повторяет `src/app/paths.py`: `ILT_DATA_DIR`, иначе `data`
в корне установки (в dev — `repoRoot/data`). `%LOCALAPPDATA%` не используется.
Ассеты Flutter (`desktop/data`) пользовательским каталогом не считаются.

## Раскладка dist

```
dist/ImageLocalizationTool/
├── desktop/   — Flutter-релиз (ImageLocalizationTool.exe, рантайм, data-ассеты)
├── sidecar/   — PyInstaller (ImageLocalizationTool.exe, _internal)
├── web/  fonts/
├── models/    — по опции сборки; иначе скачиваются первым запуском
└── data/      — настройки, проекты, кэш, лог, ключ LLM (создаётся при запуске)
```

## Структура

```
lib/src/sidecar/   — handshake, корни данных, запуск/остановка, single-instance, фокус окна
lib/src/api/       — cookie REST-клиент и SSE-ридер
lib/src/state/     — ShellState (ChangeNotifier)
lib/src/ui/        — каркас окна: пустое состояние, просмотрщик, инспектор, настройки
```
