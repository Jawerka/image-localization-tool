# Tasks: Region tabs and live transforms

**Input**: `specs/051-region-tabs-live-transform/`
**Status**: In Progress; T019–T028 complete, manual acceptance T017–T018 pending

## Phase 1: Tabs and state

- [X] T001 Split Flutter region card into text/font/transform sections with a shared draft.
- [X] T002 Add web tablist/tabpanel with keyboard navigation and per-region selection.

## Phase 2: Frozen layout and layer

- [X] T003 Add `layout_snapshot` to `TextRegion` and persist it in documents/portable projects.
- [X] T004 Emit `X-Layout-Snapshot` from base-layer and exact preview.
- [X] T005 Consume the snapshot in the final Typesetter render.
- [X] T006 Add stable padding and capture the full styled layer with negative origin.
- [X] T007 Add snapshot tests for rotation, portable round-trip and missing font.

## Phase 3: Composition

- [X] T008 Add `base-overlay` and ordered below/selected/above composition on desktop and web.
- [X] T009 Add `drafts_complete` with add/delete and composition key.

## Phase 4: Local transforms

- [X] T010 Pre-rotate arc/wave/flag/ring layers and keep warp local (Dart + JS surface).
- [X] T011 Add shared Dart/JS/Python warp fixture.
- [X] T012 Exclude skew and mesh/perspective+rotation with exact fallback and UI hint.

## Phase 5: Done and resources

- [X] T013 Add awaitable desktop Done with retry, bake polling and atomic image replacement.
- [X] T014 Add awaitable web Done with retry bodies, revision polling and result preload.
- [X] T015 Bound image/fill caches and release codecs/blobs.
- [X] T016 Add headless Chromium UI smoke for tabs, mesh fallback, Done and export.

## Phase 6: Acceptance

- [ ] T017 Manual Flutter EXE: real pages, DPI 200%, themes, 344 px.
- [ ] T018 Measure p95 frame/input-to-visible, Done time and GPU memory.
- [X] T019 Compare final render/export independently from the same snapshot.

## Phase 7: Recheck defects (2026-10-21)

Evidence: [recheck](../../docs/REGION_TABS_LIVE_TRANSFORM_RECHECK.md). Completed tasks above record delivered work; these tasks close uncovered paths before implementation can be declared complete.

- [X] T020 Preserve frozen layout through PagePipeline.typeset_image scaling; verify the worker/apply_document path with default layout_long_side=2000 and changed rotation.
- [X] T021 Synchronize web preview layout_snapshot with the Done PUT body; verify real preview -> Done without another edit, and Done before preparation completes.
- [X] T022 Retry a genuinely failed bake by submitting the correct job/version, rather than polling a terminal error; cover desktop and web without another document PUT.
- [X] T023 Use the same stable source extent on the first pre-rotated base-layer without a prior snapshot and on final render; cover rotation+arc/wave/flag/ring.

## Phase 8: Re-review fixes (2026-10-21)

Evidence: [second review](../../docs/REGION_TABS_REVIEW_T020_T023.md).

- [X] T024 Preserve a valid draft `layout_snapshot` through preview/Done and send it from desktop; cover HTTP preview at 0° → rotation 35° → snapshot request.
- [X] T025 Accept a new desktop region in the Done snapshot request by sending `drafts`; cover create-region → Done.
- [X] T026 Disable partial composition when the page switches between upscale and native render modes; compare partial/full output.
- [X] T027 Restore the failed `apply_document` plan (including `clean`) on rebake instead of always requesting `typeset`.
- [X] T028 Serialize the active-job check and submission in rebake; cover two concurrent HTTP requests producing one job.
