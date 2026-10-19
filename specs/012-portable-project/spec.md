# Feature Specification: Portable Project Package

**Feature Branch**: `012-portable-project`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: User description: "Portable project as a ZIP containing JSON markup and page images; Save / Load / Close; drag-reorder pages in the left preview list; persist order via numbered filename prefixes like 0001_ in the package. Integrate via Spec Kit / SDD."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Save a portable project with images (Priority: P1)

A user has an open chapter with pages, regions, translations, and statuses. They choose Save project (or Save as) and pick a destination. The product writes a single portable package that contains a project description and the source images for every page, in the current reading order. Opening that package later (including on another machine) does not require the original absolute paths on disk.

**Why this priority**: Without a self-contained package, work cannot be moved or backed up reliably.

**Independent Test**: Open pages, edit markup on at least one page, Save as a package, confirm the file exists and contains both the project description and the page images in order.

**Acceptance Scenarios**:

1. **Given** an open project with two or more pages and saved markup, **When** the user saves a portable project package, **Then** the package includes a project description and one source image per page.
2. **Given** a saved package, **When** the user inspects page file names inside it, **Then** names use a zero-padded numeric prefix reflecting reading order (for example `0001_…`, `0002_…`).
3. **Given** a successful Save, **When** the user continues editing without further changes that would mark dirty, **Then** the project is not shown as needing save solely because Save just completed.

---

### User Story 2 - Load a portable project (Priority: P1)

A user chooses Load project and selects a portable package. The product opens it as the working project: pages appear in the left list in package order, previews show, and regions/texts/statuses from the package are restored so the user can continue editing or typesetting.

**Why this priority**: Load is the counterpart to Save; without it the package is useless.

**Independent Test**: Load a previously saved package on a clean session and confirm page order, images, and at least one page's regions/translations match what was saved.

**Acceptance Scenarios**:

1. **Given** a valid portable package, **When** the user loads it, **Then** the left page list shows all pages in the package order and the active project is that loaded work.
2. **Given** a package created on another machine, **When** the user loads it here, **Then** pages open without needing the original absolute source paths from the other machine.
3. **Given** a damaged or non-project archive, **When** the user tries to load it, **Then** they see a clear error and the previous session project is not left half-replaced.

---

### User Story 3 - Close the project (Priority: P2)

A user chooses Close project. The working project leaves the session (empty or idle state). If there are unsaved changes since the last successful Save to a package, the product asks for confirmation before closing.

**Why this priority**: Users need a clean exit without losing silent work.

**Independent Test**: With dirty edits, Close prompts; after confirm, no pages remain active. With a clean saved state, Close does not falsely warn.

**Acceptance Scenarios**:

1. **Given** unsaved changes relative to the last package Save, **When** the user chooses Close, **Then** they are asked to confirm before the project is closed.
2. **Given** no unsaved package changes, **When** the user closes, **Then** the project leaves the session without a false dirty warning.

---

### User Story 4 - Reorder pages by dragging previews (Priority: P1)

In the left preview list, the user grabs a page card and moves it above or below other pages. The new order is kept in the working project immediately (list order and numbering). When they later Save a portable package, that order is written into the package (description order and numeric filename prefixes).

**Why this priority**: Reading order is part of the project; users must control it without renaming files by hand.

**Independent Test**: Drag page B above page A, confirm the list order flips; Save; Load in a new session; confirm B still precedes A and prefixes reflect that order.

**Acceptance Scenarios**:

1. **Given** at least two pages in the list, **When** the user drag-reorders a page, **Then** the list updates to the new order without losing selection clarity for the moved page when appropriate.
2. **Given** a new order from drag-reorder, **When** the user Saves a package, **Then** package page order and `0001_`, `0002_`, … prefixes match that order.
3. **Given** drag-reorder, **When** the user only clicks a page without dragging, **Then** that click still selects the page (reorder does not break ordinary selection).

---

### Edge Cases

- Empty project (no pages): Save is unavailable or explains that there is nothing to pack.
- Missing image referenced by the package description: Load fails with a clear message; session not half-imported.
- Very large projects: Save/Load remain usable; user is not left without progress feedback for long operations when the product already has busy indicators.
- Reorder during a running page job: order still updates; in-flight work stays tied to page identity, not list position.
- Opening a normal chapter ZIP/CBZ without a project description continues to use existing “open archive/folder” ingest, not portable Load.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to save the current working project as a single portable package containing a project description and source images for all pages.
- **FR-002**: Users MUST be able to load a portable package into a working session, restoring page images, reading order, statuses, and page documents (regions, strokes, translations, styles, and related document fields the product already persists per page).
- **FR-003**: Users MUST be able to close the working project from the session, with confirmation when there are unsaved changes relative to the last successful package Save.
- **FR-004**: Users MUST be able to reorder pages by dragging items in the left preview list; the working project MUST persist that order.
- **FR-005**: Portable packages MUST encode reading order both in the project description’s page sequence and in zero-padded numeric filename prefixes on packed images (for example `0001_`, `0002_`).
- **FR-006**: On Save, filename prefixes MUST be renumbered to match the current working order.
- **FR-007**: Load MUST treat the project description page sequence as the source of truth for order; prefixes MAY be used as a fallback when recovering order.
- **FR-008**: Existing Open files / Open folder (and ordinary chapter archives without a project description) MUST remain available and MUST NOT be replaced by portable Load.
- **FR-009**: The product MUST keep using a working session store; the portable package is import/export, not the only on-disk store for live editing.
- **FR-010**: Portable packages MUST include source images and project description; mask, clean, result, and thumb SHOULD be stored under a separate `res/` directory (not mixed with originals in `pages/`). Missing derived files MUST NOT block Save; field-level failures MUST be recorded in `pages[].errors` and API `warnings`.
- **FR-011**: File menu (or equivalent) MUST expose Load project, Save project, Save project as, and Close project; Save SHOULD be available via a common shortcut when a project is open.
- **FR-012**: After a successful package Save, the dirty state relative to that package MUST clear; edits or reorders afterward MUST mark the project dirty again.

### Key Entities

- **Portable package**: A single archive file the user moves or backs up; contains project description plus source page images.
- **Project description**: Metadata (name, languages) and ordered list of pages with status and per-page document content.
- **Working project**: The in-session project the editor edits; may be linked to a last-saved package path for Save vs Save as.
- **Page order**: Explicit reading sequence of page identities in the working project and in the package.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can Save a multi-page project to a portable package and Load it in a fresh session with page order and markup matching what was saved (verified in a structured test with at least two pages).
- **SC-002**: After drag-reordering two pages and Saving, a subsequent Load shows the new order without manual file renaming.
- **SC-003**: An invalid or incomplete package is rejected with an error the user can understand; a prior open project is not left in a half-imported state.
- **SC-004**: Close with unsaved package changes prompts before discarding; Close after a clean Save does not spuriously prompt.

## Assumptions

- Users work in the desktop app window; Flutter shell remains out of scope.
- Package format is a ZIP-based portable project with a distinguished project description file inside (extension such as `.ilt.zip` is acceptable).
- Chapter grouping in the UI, if present, follows the global page order after reorder rather than independent per-chapter queues in v1.
- Absolute paths inside the package description are not required for Load when images are packed inside the archive.
- LAN/remote inbox sync of portable packages is out of scope for this feature.
