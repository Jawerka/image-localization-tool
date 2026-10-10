# Research: 012 Portable Project

## Decision: ZIP + project.json

- **Rationale**: User asked for a single archive with JSON and images; ZIP is already used in ingest.
- **Alternatives**: JSON-only with relative paths (rejected — broken when images move); folder-as-project (worse UX than one file).

## Decision: Order = project.pages[] + 0001_ prefixes

- Store already lists pages in `project.json` array order; `_add_items` appends by natural name only at ingest.
- DnD rewrites that array. ZIP Save writes `pages/0001_name.ext` and `pages[]` in the same order.
- Load uses `pages[]` order; if missing, sort by prefix.

## Decision: Working store remains

- Unpack images under `imports/<package-stem>/` and set `source_path` there.
- Package path remembered in app state for Save vs Save as; dirty vs last save snapshot.

## Decision: No mask/clean/result in v1

- Spec FR-010; keeps packages smaller; pipeline regenerates on demand.

## Decision: Distinguish from chapter ZIP

- Require `project.json` with `kind: "ilt-project"`. Ordinary cbz/zip without it stays on open-folder/import path.
