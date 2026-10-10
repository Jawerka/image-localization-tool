# Feature Specification: Deferred Style Edits & Stepwise Undo

**Feature Branch**: `014-deferred-style-undo`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Expand Done so style settings in the right panel also wait for confirmation. Mask edits before Done must undo/redo one step at a time (Ctrl+Z / UI arrows), not wipe the whole pre-Done session."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stepwise undo of mask strokes before Done (Priority: P1)

A user paints several brush or eraser strokes without pressing Done. Each Ctrl+Z (or toolbar undo) removes only the last completed stroke. Redo restores one stroke at a time. The page is not sent for full recalculation until Done.

**Why this priority**: Current behavior undoes the entire pre-Done session at once; that is the reported defect.

**Independent Test**: Apply three separate strokes with Done still pending; undo three times; each undo removes exactly one stroke from the local draft.

**Acceptance Scenarios**:

1. **Given** three completed mask strokes and Done visible, **When** the user undoes once, **Then** only the last stroke is removed and Done remains available if other pending edits exist.
2. **Given** that state, **When** the user redoes once, **Then** that stroke returns without a server apply.
3. **Given** pending strokes, **When** the user presses Done, **Then** the accumulated document is applied (recalculate / save) as today.

---

### User Story 2 - Style panel waits for Done (Priority: P1)

A user changes font size, color, font face, uppercase, warp, translation, or block type in the right-hand region card. Those changes update the local editor state and keep Done pending. They are not flushed to the server until Done (or until the user confirms via the existing leave/discard dialog).

**Why this priority**: Users expect the same confirmation gate for style as for mask.

**Independent Test**: Change font size with mask or without; assert Done appears and no document put/typeset runs until Done.

**Acceptance Scenarios**:

1. **Given** an open page with a selected region, **When** the user changes a style field in the right panel, **Then** Done becomes (or stays) available and the change is visible in the panel without an immediate full-page apply.
2. **Given** pending style (and/or mask) edits, **When** the user presses Done, **Then** both style and mask pending edits are applied together.
3. **Given** pending style edits, **When** the user tries to leave the page, **Then** the existing unconfirmed-edits dialog still asks to confirm, discard, or stay.

---

### User Story 3 - Sticky defer while a draft session is open (Priority: P2)

If the user already has pending deferred edits and then moves or resizes a region box on the canvas, that geometry change does not force an early apply that would silently commit the draft. It stays in the same pending session until Done or discard.

**Why this priority**: Prevents accidental flush of mask/style drafts.

**Independent Test**: Paint one stroke, then nudge a box; no apply until Done.

**Acceptance Scenarios**:

1. **Given** a pending deferred session, **When** the user moves a region box, **Then** Done remains pending and no server apply runs until Done.

---

### Edge Cases

- Undo back to the pre-session baseline: Done hides; no unnecessary apply if nothing remains to commit.
- Redo after partial undo while still deferred: stays local until Done.
- Slider/field coalesce (font size drag): still one undo step per continuous field gesture, not per pointermove.
- Discard via dialog: restores last applied page document; history for that draft is cleared as today.
- Empty Done click with nothing pending: no-op.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each completed mask stroke (or lasso fill) MUST be a separate undo/redo step while Done is pending.
- **FR-002**: Undo/redo of deferred edits MUST NOT trigger document apply/save until the user presses Done (or until the draft is fully undone back to the last applied baseline and no longer pending).
- **FR-003**: Style and translation edits from the right-hand region panel MUST enter the same deferred session as mask edits and MUST wait for Done before apply.
- **FR-004**: While a deferred session is open, further document edits (including box move/resize) MUST NOT clear the session or flush early (sticky defer).
- **FR-005**: Done MUST apply the full pending document (mask strokes and style/translation changes together).
- **FR-006**: Existing leave-page / replace-project confirm-or-discard flow MUST continue to cover any deferred session (mask and/or style).
- **FR-007**: Toolbar undo/redo buttons and keyboard shortcuts MUST share the same stepwise behavior.

### Key Entities

- **Deferred session**: local editing period after the first pending edit until Done or discard.
- **Baseline**: last applied document snapshot that defines “no pending changes”.
- **Pending document**: in-memory page document including strokes and region styles not yet applied.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After N separate mask strokes before Done, exactly N undos are required to return to the pre-stroke baseline (N ≥ 3 in automated test).
- **SC-002**: Changing a style field sets the deferred/pending affordance (Done visible) without an apply call before Done.
- **SC-003**: Undo during a deferred session does not schedule document save/apply while pending edits remain.
- **SC-004**: Done after mixed mask + style edits results in a single apply of the combined document.

## Assumptions

- “Style settings” means inspector card fields that edit region content/style (translation, type, font, size, colors, uppercase, warp), not unrelated project settings.
- Coalescing within a single continuous control gesture (e.g. holding a slider) remains acceptable as one undo step.
- Server typeset/shorten behavior is unchanged aside from when apply is triggered.
