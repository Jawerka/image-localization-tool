# Data Model: 030-runtime-deployment

## Манифест (`src/app/runtime_manifest.json`, ассет `ilt-runtime-manifest-<ver>.json`)

```json
{
  "schema": 1,
  "app": "1.0.0",
  "packs": [
    {
      "id": "torch-cpu",
      "title": "PyTorch CPU (LaMa)",
      "kind": "torch",
      "platform": "win32",
      "python": "310",
      "version": "2.11.0",
      "url": "https://github.com/Jawerka/image-localization-tool/releases/download/v1.0.0/ilt-runtime-torch-cpu-win-x64-py310.7z",
      "sha256": "<64 hex>",
      "size_bytes": 178257920,
      "gpu": null
    },
    {
      "id": "torch-cu128",
      "title": "PyTorch CUDA 12.8",
      "kind": "torch",
      "platform": "win32",
      "python": "310",
      "version": "2.11.0+cu128",
      "url": "…",
      "sha256": "…",
      "size_bytes": 1342177280,
      "driver_min": 570
    },
    {
      "id": "argos",
      "title": "Argos Translate",
      "kind": "argos",
      "platform": "win32",
      "python": "310",
      "version": "1.11.1",
      "url": "…",
      "sha256": "…",
      "size_bytes": 104857600,
      "driver_min": null
    }
  ]
}
```

Правила:

- `id` уникален в пределах платформы; `kind` — `torch | argos`.
- Один установленный torch-пак на платформу; если стоят оба, активен `torch-cu128`.
- `driver_min` — минимальная major-версия драйвера NVIDIA (570).
- URL могут быть `file://` (spike/тесты) или https.

## Состояние пака (`RuntimePackState`)

| Поле | Тип | Описание |
|---|---|---|
| id | str | из манифеста |
| state | str | `available` / `downloading` / `installing` / `installed` / `error` |
| installed_version | str | из `pack.json` |
| installed_bytes | int | размер каталога |
| size_bytes | int | из манифеста |
| recommended | bool | совпадает с рекомендацией железа |
| error | str | текст последней ошибки |

## Маркер установки (`<install_root>/runtime/<id>/pack.json`)

```json
{"id": "torch-cpu", "version": "2.11.0", "sha256": "<64 hex>", "installed_at": 1791800000.0}
```

Каталог активируется, только если маркер есть и файл `site-packages` — каталог.

## Раскладка на диске

```text
<install_root>/
├── desktop/            # Flutter-хост
├── sidecar/            # PyInstaller (_internal/stdlib.zip)
├── models/             # создаётся при первом обращении
├── runtime/
│   ├── torch-cu128/
│   │   ├── pack.json
│   │   └── site-packages/{torch,torchgen,…}
│   ├── torch-cpu/
│   └── argos/
├── web/ fonts/
└── data/               # portable-режим
    ├── settings.json
    └── argos-packages/ # языковые модели Argos
```

## Рекомендация железа (`hardware.detect()`)

```json
{
  "vendor": "nvidia",
  "name": "NVIDIA GeForce RTX 5060 Laptop GPU",
  "driver": 617,
  "recommended": "torch-cu128",
  "reason": "CUDA доступна: драйвер 617 ≥ 570",
  "gpus": [{"vendor": "nvidia", "name": "…", "driver": 617}, {"vendor": "intel", "name": "Intel(R) UHD Graphics"}]
}
```

- `vendor` — `nvidia | amd | intel | none` (по основному GPU с приоритетом NVIDIA).
- `recommended` — `torch-cu128` при NVIDIA и `driver >= 570`, иначе `torch-cpu`.
- Ошибки процессов не всплывают: `vendor=none`, `reason` с причиной.

## Хранение в UI

- `SecondaryState.runtimePacks: List<RuntimePack>` — статусы из `GET /api/runtime` и SSE.
- `runtime.progress` обновляет `done/total/state/error` без полного refresh.
