# Feature Specification: Region tabs and live transforms

**Feature Branch**: `051-region-tabs-live-transform`
**Created**: 2026-10-21
**Status**: In Progress (manual acceptance T017–T018 pending)

## User Scenarios & Testing

### User Story 1 - Three region tabs (Priority: P1)

A user edits a region in Текст / Шрифт / Трансформация without applying on tab switch.

**Acceptance Scenarios**:

1. **Given** a selected region, **When** the user switches tabs, **Then** the draft input is preserved and no server request is made.
2. **Given** the inspector width 344 px and 200% text, **When** tabs are shown, **Then** labels are reachable without horizontal overflow.

### User Story 2 - Prepare once, transform locally (Priority: P1)

A user opens Трансформация, moves text, rotates it and changes arc/wave/flag/ring/mesh, seeing the result without a request per frame.

**Acceptance Scenarios**:

1. **Given** a prepared layer, **When** the user drags or changes geometry, **Then** base page, text layer and above-layer keep their order.
2. **Given** a geometry change before the preparation debounce, **When** the debounce elapses, **Then** preparation still runs.
3. **Given** arc/wave/flag/ring with rotation, **When** the angle changes, **Then** the layer is re-prepared already rotated and warp stays local.
4. **Given** mesh/perspective with rotation or skew, **When** the user edits, **Then** an exact server preview is used and the UI says so.

### User Story 3 - Done is reliable (Priority: P1)

The user presses Готово once; the shown layout is baked and can be retried after a failure.

**Acceptance Scenarios**:

1. **Given** a prepared draft, **When** Done is pressed, **Then** the document is saved, the result revision is awaited and the decoded image replaces the preview atomically.
2. **Given** a failed PUT, bake or PNG, **When** Done is pressed again, **Then** only the failed step is retried.
3. **Given** a rotation change after preparation, **When** Done finishes, **Then** lines and font size equal the prepared snapshot.

## Requirements

- **FR-001**: `layout_snapshot` is saved in the region and consumed by final rendering.
- **FR-002**: Base-layer padding is stable across rotation/warp/bend.
- **FR-003**: Base-layer and exact preview return the snapshot via `X-Layout-Snapshot`.
- **FR-004**: Local composition is ordered as `base-page` -> selected layer -> `base-overlay`.
- **FR-005**: `drafts_complete` declares a full document snapshot including add/delete.
- **FR-006**: Desktop and web Done are awaitable and retry failed save/bake/image steps.
- **FR-007**: Skew-fallback is explained in the transform tab.
- **FR-008**: Image caches are byte-bounded and codecs are released.

## Out of scope

- Pixel-identical GPU and CPU rasterization.
- Local mesh/perspective combined with rotation and local skew; documented exact fallback.
- Manual EXE/DPI/p95/GPU-memory acceptance.
