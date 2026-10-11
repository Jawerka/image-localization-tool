# Контракт: Runtime API (030)

Все эндпоинты — под существующей cookie-авторизацией `/api/*` (см. `src/app/server.py`), кроме
случая, когда запрос сделан в том же порядке, что и раньше (сессия как у остальных).

## GET /api/runtime

```json
{
  "platform": "win32",
  "python": "310",
  "packs": [
    {
      "id": "torch-cpu",
      "title": "PyTorch CPU (LaMa)",
      "kind": "torch",
      "version": "2.11.0",
      "size_bytes": 178257920,
      "state": "installed",
      "installed_version": "2.11.0",
      "installed_bytes": 431104000,
      "recommended": false,
      "error": ""
    }
  ],
  "hardware": {
    "vendor": "nvidia",
    "name": "NVIDIA GeForce RTX 5060 Laptop GPU",
    "driver": 617,
    "recommended": "torch-cu128",
    "reason": "CUDA доступна: драйвер 617 ≥ 570"
  },
  "torch_ready": false,
  "argos_ready": false,
  "device": "auto",
  "device_effective": "cpu",
  "download": {"id": "", "state": "idle"}
}
```

- `device_effective` — что даст `auto` сейчас (`cuda` только при активном torch c CUDA).
- `download` — текущая фоновая установка (если нет — `idle`).

## POST /api/runtime/download

Тело: `{"id": "torch-cu128"}`.

- Пак есть в манифесте для платформы → 202 `{"ok": true, "id": "…"}`.
- Уже установлен → 200 `{"ok": true, "installed": true}` (no-op).
- Идёт другая загрузка → 409 `{"error": "Другая загрузка уже идёт"}`.
- Неизвестный id → 400 `{"error": "Неизвестный компонент"}`.

Прогресс — SSE-событие (существующий `/api/events`):

```json
{
  "type": "runtime.progress",
  "payload": {
    "id": "torch-cu128",
    "status": "downloading|installing|installed|error",
    "done": 104857600,
    "total": 1342177280,
    "error": ""
  }
}
```

## POST /api/runtime/remove

Тело: `{"id": "torch-cpu"}` → 200 `{"ok": true}` (нет пака — тоже ok, идемпотентно).
Во время загрузки удаление запрещено: 409.

## GET /api/bootstrap (дополнение)

```json
"runtime": {
  "installed": ["torch-cpu"],
  "recommended": "torch-cu128",
  "torch_ready": false,
  "argos_ready": false,
  "device_effective": "cpu"
}
```

## CLI

```
ImageLocalizationTool.exe --deploy cpu|cuda|argos|models|all
```

- `--deploy` без `--headless/--api/--browser`: работа без окна, прогресс в stdout, exit 0/1.
- `models` — детектор + LaMa + шрифты (как `scripts/setup_models.py`).
- `cpu`/`cuda`/`argos` — соответствующий пак из манифеста.
- `all` — `models` + `argos` + torch по `hardware.detect()["recommended"]`.
- Повторный запуск: «<id>: уже установлено», exit 0.
