# Data Model: Windows staged update

## Release metadata

The root of the portable update bundle contains `release.json`:

- `schema`: required integer `1`.
- `version`: required dotted numeric version with 2–4 numeric components.
- `platform`: required string `windows-x64`.
- `host`: required relative path `desktop/ImageLocalizationTool.exe`.
- `sidecar`: required relative path `sidecar/ImageLocalizationTool.exe`.
- `web`: required relative path `web/index.html`.

Validation rejects absolute paths, traversal segments, links/reparse points for required entries, missing files, and version mismatch between metadata and the bundle name when a name is supplied.

## Previous-release pointer

`previous.json` is stored beside the active install root:

- `schema`: required integer `1`.
- `folder`: relative sibling folder name containing the previous app files.
- `version`: version recorded in that previous folder's `release.json`.
- `updated_at`: UTC timestamp for diagnostics.

The pointer is written through a same-directory temporary file and replacement. It cannot refer outside the updater's parent directory.

## Persistent directories

The following directories remain at the active install root across version changes: `data`, `models`, `runtime`, `.resources`, `.downloads`, `.builtin`, and `components`. They are moved between the active and staged release during activation/rollback; their contents are not rewritten by the updater.
