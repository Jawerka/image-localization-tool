# Feature Specification: Editor Shell v2 Port

**Feature Branch**: `020-editor-shell-polish`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: Port shell v2 from `web/mockups/next` into live `web/`: CSS/HTML plus JS wiring for floating dock, collapsible panels, popovers; preserve or sync `data-role` for e2e/JS tests; generate `tokens.json` from live tokens; parity map for keys/gestures; Flutter out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Canvas-first editor chrome (Priority: P1)

A translator working a page sees a slim top bar, a dominant scene with floating page, a bottom floating tool dock (view/layers/tools/brush/zoom), and collapsible page/inspector rails — matching the approved mockups in `web/mockups/next` for the editor screen.

**Why this priority**: This is the core daily workspace; without it the visual redesign does not ship.

**Independent Test**: Open a project page in the live app; compare layout regions to `next/main-editor.html` (dark theme, scale 100%).

**Acceptance Scenarios**:

1. **Given** a page is open in the editor, **When** the shell renders, **Then** tools live in a bottom floating dock (not a second full-width viewer bar as the sole tool strip).
2. **Given** the editor is open, **When** the user toggles the left or right panel controls, **Then** the pages rail or inspector collapses/expands without losing document state.
3. **Given** brush tool is active, **When** the user opens brush size from the dock, **Then** a popover appears and changing size updates the brush radius used for painting.

---

### User Story 2 - Theme and UI scale still work (Priority: P1)

Users keep light/dark (and system) themes and UI scale 100–150% via settings; the new chrome sizes through `--ui-scale` (not mockup-only CSS `zoom`).

**Why this priority**: Existing accessibility and preference contracts must not regress.

**Independent Test**: Set theme dark/light and scale 100/125/150; walk editor, empty, and batch layouts.

**Acceptance Scenarios**:

1. **Given** UI scale 150%, **When** the editor opens, **Then** chrome metrics grow via `--ui-scale` and remain usable (no clipped primary controls).
2. **Given** light theme, **When** the editor opens, **Then** shell uses light tokens with readable contrast on primary chrome.

---

### User Story 3 - Automation stays green (Priority: P1)

Automated UI smoke and JS unit tests continue to pass after the shell port; `data-role` selectors used by tests are preserved or tests are updated in the same change.

**Why this priority**: Prevents silent breakage of the live app contract during a radical chrome change.

**Independent Test**: Run `pytest tests/e2e/test_ui_smoke.py -m ui` and `npm run test:js`.

**Acceptance Scenarios**:

1. **Given** the ported shell, **When** UI smoke runs, **Then** all tests pass.
2. **Given** the ported shell, **When** JS unit tests run, **Then** all tests pass (including any updated wiring coverage).

---

### User Story 4 - Design tokens export for Flutter (Priority: P2)

Chrome metrics and palette used by the live UI are exported to a machine-readable `tokens.json` generated from `web/css/tokens.css`, so a later Flutter client can share the same numbers.

**Why this priority**: Unblocks Flutter parity without blocking the HTML ship.

**Independent Test**: Run the generator script; confirm `tokens.json` keys include panel widths, toolbar height, and core colors matching CSS.

**Acceptance Scenarios**:

1. **Given** live `tokens.css` after the v2 merge, **When** the generator runs, **Then** `tokens.json` is written/updated and matches those CSS custom properties.

### Edge Cases

- Empty project / no page selected: empty and batch shells remain usable and match `next` counterparts at a glance.
- Panel collapsed: keyboard shortcuts and dock tools still work; Done chip behavior from prior features remains.
- HTTP vs file://: live app must not depend on `sprite.js`; icons come from `web/icons/icons.svg`.

## Requirements *(mandatory)*

- **FR-001**: Live desktop UI MUST adopt the shell v2 visual structure from `web/mockups/next` for editor, empty, and batch main screens (slim app bar, floating dock, collapsible rails, scene treatment).
- **FR-002**: Dock, panel collapse, and brush-size (and similar) popovers MUST be wired in live JS so they are interactive, not static markup only.
- **FR-003**: UI scale MUST continue to use `--ui-scale` + `calc()` in live CSS; mockup `zoom` MUST NOT be required for live scale.
- **FR-004**: New icons MUST be added to `web/icons/icons.svg`; live UI MUST NOT load `web/mockups/next/sprite.js`.
- **FR-005**: `data-role` attributes required by existing e2e/JS tests MUST be preserved, or those tests MUST be updated in the same feature so smoke and unit suites pass.
- **FR-006**: A script under `scripts/` MUST generate `tokens.json` from live `web/css/tokens.css` (design reference remains `next/tokens-v2.css`).
- **FR-007**: Planning artifacts MUST include a parity map for keyboard/gestures/modals and an industry-pattern table with URLs.
- **FR-008**: This feature MUST NOT introduce Flutter code, a Python `--api` mode, or remove pywebview.
- **FR-009**: HTTP API contracts MUST remain unchanged.

## Success Criteria

- **SC-001**: Visual walkthrough of live editor/empty/batch at light and dark × scales 100/125/150 shows shell v2 regions without broken primary controls.
- **SC-002**: `pytest tests/e2e/test_ui_smoke.py -m ui` passes.
- **SC-003**: `npm run test:js` passes on Node ≥ 21.
- **SC-004**: Generated `tokens.json` lists `--pages-w`, `--inspector-w`, `--toolbar-h`, and core color tokens consistent with `web/css/tokens.css`.

## Assumptions

- Approved visual target is the existing `web/mockups/next` set (12 screens + hub + states reference).
- Prior editor behavior (deferred Done, mask draft, inspector autosave) stays unless chrome relocation requires selector updates only.
- Flutter migration is a later feature; this feature only prepares tokens and live HTML parity.
