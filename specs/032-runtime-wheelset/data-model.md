# Data Model: Runtime Wheelset (schema 2)

**Feature**: 032-runtime-wheelset | **Date**: 2026-10-11

## 1. Манифест рантайма (schema 2)

Релизный ассет `ilt-runtime-manifest-1.0.1.json` и встроенная копия `src/app/runtime_manifest.json`.

```json
{
  "schema": 2,
  "app": "1.0.1",
  "packs": [PackRecord, ...]
}
```

Правила: `packs[]` — записи обеих платформ; клиент фильтрует по `os` + `python`; невалидная запись
пропускается. Плейсхолдеры без sha256 не считаются установочными (база синхронно тянет релизный манифест).

## 2. PackRecord (`format: "wheels"`)

| Поле | Тип | Правило |
|------|-----|---------|
| `id` | string | `torch-cpu` / `torch-cu128` / `argos` |
| `title` | string | человекочитаемое имя |
| `kind` | string | `torch` / `argos` |
| `os` | string | `win` / `linux` |
| `arch` | string | `x64` |
| `python` | string | `310` |
| `version` | string | версия верхнего пакета (напр. `2.11.0+cpu`) |
| `format` | string | `wheels` |
| `files[]` | WheelFile[] | непустой |
| `size_bytes` | int | сумма `files[].size_bytes` |
| `driver_min` | int? | только `torch-cu128` (570) |

## 3. WheelFile

| Поле | Тип | Правило |
|------|-----|---------|
| `name` | string | имя файла колеса (уникально в записи; из него берётся URL-хвост при `%2B`-декоде) |
| `url` | string | абсолютный https URL CDN (`files.pythonhosted.org` / `download.pytorch.org`) |
| `sha256` | string | 64 hex |
| `size_bytes` | int | > 0 |

Ограничение целостности: для каждой wheels-записи `size_bytes == Σ files[].size_bytes`;
`len(sha256) == 64` и все символы — hex; `size_bytes > 0`.

## 4. ArchiveRecord (совместимость schema 1)

Поля как в 1.0.0: `id`, `title`, `kind`, `os`, `arch`, `python`, `version`, `url`, `sha256`, `size_bytes`,
`driver_min?`; `format` отсутствует или `"archive"`. Обрабатывается py7zr-веткой без изменений.

## 5. Лок-сводка (build-артефакт, не коммитится)

`dist/locks/<id>-<os>.json` — PackRecord (`format:"wheels"`) без GitHub-URL-базы (URL файлов абсолютные).
`dist/locks/packs.json` — массив записей (win+linux или linux), вход `build-runtime-manifest.py`.

## 6. Пин-файл лока (в репозитории)

`locks/py310-win.lock`, `locks/py310-linux.lock` — полный freeze по алфавиту:

```text
# python 3.10, <os>, torch 2.11.0 / argostranslate 1.11.0
certifi==2026.1.4
filelock==3.20.0
...
torch==2.11.0+cpu
```

CI обязан перегенерировать linux-лок и сравнить с закоммиченным (побайтово или по множеству строк —
решение реализации: по содержимому, канонизация сортировкой).

## 7. Маркер установки `runtime/<id>/pack.json`

```json
{
  "id": "torch-cpu",
  "version": "2.11.0+cpu",
  "format": "wheels",
  "files": {"torch-2.11.0+cpu-cp310-cp310-win_amd64.whl": "<sha256>", "...": "..."},
  "installed_at": 1780000000.0
}
```

Archive-ветка пишет `sha256` верхнего уровня и `format: "archive"` (совместимо с чтением старых маркеров:
`files` опционально).

## 8. Кэш гейта `build/deep.json` (не коммитится)

```json
{
  "schema": 1,
  "entries": {
    "<sha256(setup|portable|server|manifest)>": {
      "checked_at": 1780000000.0,
      "ok": true,
      "detail": "torch-cpu установлен, import torch ok"
    }
  }
}
```

Ключ — конкатенация sha256 доступных артефактов (`setup`, `portable`, `server`, `manifest`); отсутствующие
в каталоге ассеты в ключ не входят. Прогон Tier 2 с известным ключом и `ok: true` — skip.

## 9. Состояния установки пака

```text
available → downloading → installing → installed
                ↘ error ↗ (повтор → downloading)
```

- `downloading`: `done`/`total` — байты всех файлов; `installing`: распаковка.
- Каталоги: `runtime/<id>.part/` (файлы `.part` на каждый файл), `runtime/<id>.tmp/` (распаковка с
  `site-packages`), затем atomic rename → `runtime/<id>/`.
- Ошибка в любой момент: `.part` и `.tmp` удаляются, каталог пака не тронут; повтор начинает заново
  (частично скачанные файлы не переиспользуются).
