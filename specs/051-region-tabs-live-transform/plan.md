# Implementation Plan: Region tabs and live transforms

**Feature**: `051-region-tabs-live-transform`
**Status**: In Progress; manual acceptance T017–T018 pending

## Approach

1. Split the region card into three tab panels and keep draft state outside panels.
2. Add a saved `layout_snapshot` to `TextRegion`; base-layer/exact preview emit it as `X-Layout-Snapshot`; the client stores it in the document; the final render consumes frozen lines.
3. Use a stable layer padding independent of rotation/warp/bend. Capture the styled layer before page insertion so origin may be negative.
4. Prepare `base-page`, selected RGBA layer and `base-overlay`; draw them in document order. `drafts_complete` enables add/delete.
5. For arc/wave/flag/ring + rotation, prepare the layer already rotated and apply only warp locally in Dart/JS.
6. Make Done awaitable on both surfaces: save, poll result revision, preload/decode the image, then clear the draft. Keep retry bodies and expose readable errors.
7. Exclude skew and mesh/perspective+rotation from local mode with an exact fallback and a visible hint.
8. Bound image caches and release codecs/canvas textures on replacement and errors.

## Contracts

- `POST /api/pages/{id}/preview-region`:
  - `mode`: `exact | base-layer | base-page | base-overlay`
  - `drafts_complete: bool`
  - `apply_rotation: bool`
  - response headers: `X-Layout-Snapshot`, `X-Layer-Anchor-X/Y`, offsets.
- Document region: `layout_snapshot {version, layout_key, font_size, font, lines, anchor}`.

## Verification

- `tests/unit`, `tests/js`, `apps/desktop/test`, `tests/e2e/test_ui_smoke.py`.
- Shared fixture `tests/fixtures/local_warp_samples.json` for Dart/JS/Python parameters.
- Manual EXE/DPI/p95/GPU memory remains a release gate.
