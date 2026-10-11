# ilt_desktop — Flutter-хост Image Localization Tool

Поставляемое приложение (026 cutover): в dist хост лежит в `desktop/`, сам
запускает замороженный сайдкар из `sidecar/` (`--api --parent-pid`), читает
handshake (`api.json` / stdout), ходит в локальный HTTP с cookie `ilt_session`
и подписывается на SSE `/api/events`. В исходниках сайдкар поднимается как
`python -m src.app --api`.

## SDK

- Pin: **Flutter ≥ 3.47.7** stable (для сборки — Visual Studio 2022
  с Desktop C++). `environment.sdk: ^3.12.0` — совместимый пол.

## Команды

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

Корень данных повторяет `src/app/paths.py`: портативный `data` в корне
установки, иначе `%LOCALAPPDATA%\ImageLocalizationTool`. Ассеты Flutter
(`desktop/data`) пользовательским каталогом не считаются.

## Раскладка dist

```
dist/ImageLocalizationTool/
├── desktop/   — Flutter-релиз (ImageLocalizationTool.exe, рантайм, data-ассеты)
├── sidecar/   — PyInstaller (ImageLocalizationTool.exe, _internal)
├── web/  fonts/
├── models/    — по опции сборки; иначе скачиваются первым запуском
└── data/      — по желанию, портативный режим
```

## Структура

```
lib/src/sidecar/   — handshake, корни данных, запуск/остановка, single-instance, фокус окна
lib/src/api/       — cookie REST-клиент и SSE-ридер
lib/src/state/     — ShellState (ChangeNotifier)
lib/src/ui/        — каркас shell v2 (экраны — 022–025)
```
