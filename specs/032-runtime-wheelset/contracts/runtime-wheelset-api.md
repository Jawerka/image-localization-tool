# Contract: Runtime API / CLI / env (wheelset)

**Feature**: 032-runtime-wheelset

Совместимые дополнения существующих контрактов (030). Удаления/переименования полей нет.

## `GET /api/runtime` — дополнение записи пака

К существующим полям записи пака добавляются:

| Поле | Тип | Значение |
|------|-----|----------|
| `format` | string | `"wheels"` или `"archive"` |
| `source` | string | человекочитаемый источник файлов: `"PyPI"`, `"PyTorch CDN"`, `"GitHub releases"` (archive); для wheels — по хосту первого файла |

`size_bytes` — теперь суммарный размер всех файлов записи (для wheels — та же семантика, что и раньше:
размер пака в байтах). Прогресс-события не меняются:

## SSE `runtime.progress`

`{id, state, done, total, error}` — без изменений; `total` для wheels = `size_bytes` записи,
`done` растёт по мере скачивания файлов; `installing` — распаковка.

## `POST /api/runtime/download` / `POST /api/runtime/remove`

Контракт без изменений.

## CLI

- `ImageLocalizationTool.exe --deploy cpu|cuda|argos|models|all` — без изменений; внутри:
  wheels-запись ставится пофайлово и идемпотентно, ошибка — exit 1.
- `python -m src.app --deploy …` — то же в dev-режиме.

## Переменные среды

| Переменная | Назначение |
|------------|------------|
| `ILT_RUNTIME_MANIFEST_URL` | источник манифеста (файл:// или https) — своё зеркало; формат schema 1/2 |
| `ILT_INSTALL_ROOT` | корень раскладки (тесты/e2e) — без изменений |
| `ILT_TORCH_INDEX_URL` | (сборка) переопределение torch-индекса генератора локов |

## Раскладка (не меняется)

```text
<install_root>/runtime/<id>/site-packages/…   # содержимое колёс
<install_root>/runtime/<id>/pack.json         # маркер (data-model.md §7)
<install_root>/runtime/<id>.part/             # временные файлы скачивания (удаляются)
<install_root>/runtime/<id>.tmp/              # временная распаковка (удаляется)
```

## Порядок активации (не меняется)

`torch-cu128` → `torch-cpu` → `argos`; `site-packages` в `sys.path`, `torch/lib` — в DLL-поиск Windows.
