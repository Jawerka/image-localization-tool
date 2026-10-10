# Contract: Portable Project API + ZIP

## ZIP layout (`schema_version: 2`)

```
project.ilt.zip
├── project.json
├── pages/          # только исходники (порядок чтения)
│   ├── 0001_<name>.<ext>
│   └── 0002_<name>.<ext>
└── res/            # mask, clean, result, thumb
    ├── 0001_<name>.mask.png
    ├── 0001_<name>.clean.png
    ├── 0001_<name>.result.png
    └── 0001_<name>.thumb.jpg
```

`schema_version: 1` — только `pages/` + JSON (без `res/`); Load поддерживается.

`project.json` top-level: `kind: "ilt-project"`, `schema_version`, `name`, `source_lang`, `target_lang`, `pages[]`.

Each `pages[]` entry:

- `image` — path under `pages/` (required for pack inclusion)
- `mask`, `clean`, `result`, `thumb` — path under `res/` or `null`
- `document` — object or `null`
- `errors` — string[] per-page field failures on last Save (v2)

## Resilience

- Save: per-field failures → `pages[].errors`, top-level `warnings` in API response; ZIP written if ≥1 page has `image`.
- Load: missing optional `res/` files → warning; missing required `image` for a page → skip page + warning; zero imported pages → error.

## HTTP

### POST `/api/project/reorder`

```json
{ "page_ids": ["p2", "p1", "p3"] }
```

### POST `/api/project/package/save`

```json
{ "path": "C:/.../foo.ilt.zip" }
```

Response may include `warnings: string[]`.

### POST `/api/project/package/load`

```json
{ "path": "C:/.../foo.ilt.zip" }
```

Response may include `warnings: string[]`.

### POST `/api/project/close`

```json
{ "force": false }
```

If dirty and not force → 409 `{ "dirty": true }`.

### GET `/api/project/package/status`

```json
{ "path": "...|null", "dirty": true }
```

## Dialogs (native)

- `open_project_package()` → path to `.ilt.zip` or null
- `save_project_package(default_name)` → path or null

## Open / drop / import

ZIP с валидным корневым `project.json` (`kind: "ilt-project"`) через общий «Открыть», drag-and-drop или `POST /api/import` загружается так же, как `POST /api/project/package/load`. Обычные CBZ/CBR без manifest — прежний chapter-ingest.
