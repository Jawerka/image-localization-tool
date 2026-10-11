# Quickstart: 021 Flutter Shell Host

## Python sidecar (dev)

```powershell
# обычный sidecar: печатает JSON handshake в stdout и пишет api.json
python -m src.app --api

# с вотчдогом родителя (pid текущей оболочки)
python -m src.app --api --parent-pid $PID

# LAN — только явным флагом
python -m src.app --api --remote
```

Проверка вручную:

```powershell
$line = python -m src.app --api | Select-Object -First 1
$info = $line | ConvertFrom-Json
curl.exe -H "Cookie: ilt_session=$($info.token)" "http://127.0.0.1:$($info.port)/api/bootstrap"
```

## Flutter host (dev)

```powershell
cd apps\desktop
# локальный SDK 3.44.0; целевой pin ≥ 3.47.7 зафиксирован в research.md
flutter pub get
flutter analyze
flutter test

# обычный запуск: хост сам поднимет python -m src.app --api
flutter run -d windows

# attach: подключиться к уже запущенному sidecar (без spawn/kill)
flutter run -d windows --dart-define=ILT_ATTACH=1
```

## Контрольные точки

- Закрыть host → `Get-Process python` не содержит sidecar; `api.json` удалён.
- Второй запуск exe/`flutter run` (без attach) → первое окно получает путь, второе завершается.
- `python -m src.app` (pywebview) — без изменений.
