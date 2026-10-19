# Feature Specification: Floating Done Chip

**Feature Branch**: `016-floating-done`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: User description: "Move Done out of the toolbar to a floating top chip like bottom progress; horizontally draggable; can return to center."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Floating Done on pending edits (Priority: P1)

When the user has unconfirmed mask/style edits, a «Готово» chip appears at the top center of the editing stage (not in the toolbar). Progress remains at the bottom.

**Acceptance Scenarios**:

1. **Given** deferred edits pending, **When** the stage is visible, **Then** «Готово» appears as a top floating chip and is absent from the toolbar.
2. **Given** no deferred edits, **When** the UI updates, **Then** the chip is hidden.

### User Story 2 - Horizontal drag and recenter (Priority: P1)

The user can drag the chip left/right along the top. Releasing near the center snaps it back; double-click recenters. A drag does not commit edits; a click without meaningful move does.

**Acceptance Scenarios**:

1. **Given** the chip visible, **When** the user drags horizontally past a small threshold, **Then** the chip moves and releasing near center snaps to center.
2. **Given** a drag occurred, **When** the pointer is released, **Then** edits are not committed by that gesture.
3. **Given** a short click without drag, **When** released, **Then** Done commits as today.
4. **Given** the chip off-center, **When** the user double-clicks it, **Then** it returns to center.

## Requirements *(mandatory)*

- **FR-001**: Done MUST NOT live in the viewer toolbar.
- **FR-002**: Done MUST appear as a top overlay on the stage host when deferred edits are pending.
- **FR-003**: Chip MUST be horizontally draggable within the stage host; vertical position stays at the top.
- **FR-004**: Soft-snap to center on release when near center; double-click MUST force center.
- **FR-005**: Drag beyond threshold MUST NOT trigger commit; tap MUST trigger commit.
- **FR-006**: Horizontal position MAY persist for the browser session (sessionStorage).

## Success Criteria

- **SC-001**: Chip hidden when `deferredApply` is false; shown when true.
- **SC-002**: Unit tests cover clamp, near-center snap, and click-vs-drag threshold.
