# Feature Specification: Editor Session & Dual Mask Tools

**Feature Branch**: `015-editor-session-tools`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Saving must not jump to the first page; persist selected page, zoom, and pan. Add Fit-width. Merge brush/eraser and lasso add/subtract via LMB/RMB with tooltips."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Save keeps the current page (Priority: P1)

A user works on a middle page, saves the project package, and remains on that same page. The UI does not jump to the first image.

**Independent Test**: Open a multi-page project, select page 2+, save; active page stays the same.

**Acceptance Scenarios**:

1. **Given** page N is active (N > 1), **When** the user saves, **Then** page N remains active and visible.

---

### User Story 2 - Session viewport restored on open (Priority: P1)

A user saves while zoomed and scrolled on a page. After closing and reopening the package, the same page, zoom mode/level, and scroll position are restored.

**Independent Test**: Save with fit-width and non-zero scroll; reload package; compare session fields.

**Acceptance Scenarios**:

1. **Given** a saved package with editor session data, **When** the user opens it, **Then** active page, zoom, and scroll match what was saved.

---

### User Story 3 - Fit width (Priority: P2)

A user clicks «По ширине» next to zoom controls. The image scales so its width matches the editing stage (height may scroll).

**Independent Test**: Tall image; fit-width scale equals stage width / image width.

**Acceptance Scenarios**:

1. **Given** an image wider or taller than the stage, **When** «По ширине» is pressed, **Then** the frame width matches the stage content width (minus padding).

---

### User Story 4 - Dual-button brush and lasso (Priority: P1)

Brush and eraser are one tool: LMB paints, RMB erases (tooltip explains). Lasso is one tool: LMB adds mask fill, RMB subtracts (tooltip). Separate Eraser toolbar button is gone.

**Independent Test**: With brush tool, LMB vs RMB stroke modes; with lasso, LMB fill vs RMB erase_fill.

**Acceptance Scenarios**:

1. **Given** brush tool, **When** LMB strokes, **Then** mode is paint; RMB strokes → erase.
2. **Given** lasso tool, **When** LMB closes a polygon, **Then** fill adds mask; RMB polygon → subtracts.

---

### Edge Cases

- Saved active page id missing after reorder/import: fall back to first page.
- Packages without editor field: open as today (first or preserved if already open).
- Fit vs fit-width both available; fit still fits entire image in view.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Saving a package MUST NOT force selection to the first page when the current page still exists.
- **FR-002**: Package save MUST store editor session (active page, zoom, scroll).
- **FR-003**: Package load MUST restore editor session when present.
- **FR-004**: UI MUST provide «По ширине» zoom that fits image width to the stage.
- **FR-005**: Brush tool MUST paint on LMB and erase on RMB; Eraser tool button MUST be removed.
- **FR-006**: Lasso tool MUST add fill on LMB and subtract fill on RMB.
- **FR-007**: Brush and Lasso buttons MUST expose LMB/RMB behavior via tooltip/title.

## Success Criteria *(mandatory)*

- **SC-001**: After save on page index ≥ 2, active page id unchanged.
- **SC-002**: Round-trip pack/unpack preserves editor session fields.
- **SC-003**: Fit-width scale = (stageWidth − padding) / imageWidth.
- **SC-004**: Automated checks cover brush/lasso dual modes and no eraser tool entry.

## Assumptions

- Editor session is last-snapshot (not per-page camera map).
- Viewport persistence does not affect exported image pixels.
