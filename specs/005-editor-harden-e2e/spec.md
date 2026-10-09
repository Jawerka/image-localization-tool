# Feature Specification: Editor Harden + Done/Mask E2E

**Feature Branch**: `005-editor-harden-e2e`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Inspector card UI stability across full HTML rebuild (preserve open/focus/scroll for card details); automated e2e for local mask draft while editing and «Готово» (deferApply commit). Closes tech-debt C11–C13. Flutter out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Card sections stay as the user left them (Priority: P1)

While editing a selected region, the inspector rebuilds the card HTML on many document updates. If the user collapsed or expanded «Искажение» / «Стили проекта» (or similar card `<details>`), that open/closed state survives the next rebuild. Focus and caret in translation (and scroll of the region list) continue to survive as today.

**Why this priority**: Full `innerHTML` rebuild currently hard-opens details; users lose place mid-edit.

**Independent Test**: Open a region card, close the warp details, change translation (or another field that triggers rebuild), confirm details stay closed and focus returns to the field.

**Acceptance Scenarios**:

1. **Given** a selected region card with warp (or project-styles) details closed by the user, **When** the inspector rebuilds after an edit, **Then** those details remain closed.
2. **Given** those details open by the user, **When** the inspector rebuilds, **Then** they remain open.
3. **Given** the caret in the translation field, **When** the inspector rebuilds from that edit, **Then** focus and selection range are restored (existing behavior kept).

---

### User Story 2 - Mask shows immediately while brush strokes are deferred (Priority: P1)

With the mask layer on, painting with the brush (or eraser) updates a local mask overlay right away without waiting for the server job. The «Готово» control appears while deferred edits are pending.

**Why this priority**: Users need to see ink coverage before committing; this is SC-002 of the editor flow.

**Independent Test**: After translate, enable mask + brush, paint a stroke, assert local mask overlay is visible and «Готово» is enabled.

**Acceptance Scenarios**:

1. **Given** a ready page with mask visible and brush tool, **When** the user paints a stroke, **Then** a local mask draft overlay reflects the stroke before server apply.
2. **Given** deferred brush edits pending, **When** the toolbar updates, **Then** «Готово» is visible and enabled.

---

### User Story 3 - «Готово» commits deferred mask edits (Priority: P1)

Activating «Готово» ends the deferred-apply state and starts the normal save/apply path so the server can refresh the mask. The button returns to hidden/disabled when nothing is deferred.

**Why this priority**: Without commit, edits never leave the client draft.

**Independent Test**: After a deferred stroke, click «Готово»; assert deferred UI clears (button hidden) and a document save/apply request is issued.

**Acceptance Scenarios**:

1. **Given** pending deferred edits, **When** the user activates «Готово», **Then** deferred-apply mode ends and a save/apply of the document is requested.
2. **Given** no deferred edits, **When** the toolbar renders, **Then** «Готово» stays hidden or disabled.

---

### Edge Cases

- Rebuild with no selected region: no crash; empty/list states unchanged.
- Switching pages clears or correctly scopes local mask draft to the active page.
- Flutter shell remains out of scope.
- Full virtual DOM rewrite of the inspector is out of scope; preserve UI state across the existing rebuild path.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Region-card `<details>` open/closed state that the user set MUST survive inspector HTML rebuild for the same selected region.
- **FR-002**: Focus/caret restoration and region-list scroll restoration MUST continue to work across rebuild.
- **FR-003**: While brush/eraser strokes are deferred, the viewer MUST show a local mask draft overlay of current strokes when the mask layer is relevant.
- **FR-004**: «Готово» MUST commit deferred edits (end deferApply and trigger save/apply).
- **FR-005**: An automated UI e2e MUST cover local mask draft visibility after a stroke and «Готово» commit clearing deferred UI.
- **FR-006**: This feature MUST NOT replace the desktop shell with Flutter.

### Key Entities

- **Deferred apply**: client flag that holds document edits (strokes) until «Готово».
- **Local mask draft**: canvas/overlay painted from current strokes until server mask catches up.
- **Card UI snapshot**: open details keys, focused field, selection, list scroll.

## Success Criteria *(mandatory)*

- **SC-001**: Manual or automated check: closing warp details, editing translation, details still closed.
- **SC-002**: E2E: stroke → local mask draft visible → «Готово» visible → click → deferred control cleared and save/apply observed.
- **SC-003**: No regression of existing UI smoke (open/translate/edit/export).

## Assumptions

- Existing deferApply / maskLocal implementation is the baseline; harden and test rather than redesign.
- Hardcoded `open` on card details is the main C11 gap beyond focus/scroll already partially handled.
- FakeWorker-based Playwright harness from `tests/e2e/test_ui_smoke.py` is the e2e vehicle.
