# Data Model: Portable Project

## PortablePackage (on disk)

| Field | Type | Notes |
|-------|------|--------|
| kind | `"ilt-project"` | Required |
| schema_version | int | Start at `1` |
| name | string | Project display name |
| source_lang | string | |
| target_lang | string | |
| pages | PageEntry[] | **Reading order** |

### PageEntry

| Field | Type | Notes |
|-------|------|--------|
| id | string | Stable page id |
| name | string | Original basename without order prefix |
| status | string | Store status string |
| image | string | Relative path e.g. `pages/0001_cover.png` |
| document | object \| null | Serialized PageDocument |

## Store extensions

- `reorder_pages(project_id, page_ids: list[str])` — rewrite `project["pages"]` to match `page_ids` (must be a permutation of existing ids).
- Session (app/state, not necessarily store file): `package_path`, `package_dirty` for active project.

## Dirty

Dirty when: document/page/settings change after last successful Save/Load of package, or page reorder. Clear dirty on successful Save or Load.
