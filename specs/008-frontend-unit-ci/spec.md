# Feature Specification: Frontend Unit + CI Expand

**Feature Branch**: `008-frontend-unit-ci`

**Created**: 2026-10-09

**Status**: Draft

**Input**: "Frontend unit coverage for mask-draft / defer-related helpers and pipeline warning text; expand CI with a Node JS job; add missing typesetter pivot/rotation unit (inventory 23 + bit of 14). Playwright e2e Done/mask already exists. Flutter out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Mask stroke painting is unit-tested (Priority: P1)

Maintainers can run Node unit tests that verify brush/eraser stroke painting onto a mask canvas context matches the product rules (radius, paint vs erase colors, single-point and polyline), without launching Playwright.

**Acceptance**: Node tests pass for paint and erase strokes; viewer uses the shared helper.

### User Story 2 - Deferred-apply / draft policy helpers are unit-tested (Priority: P1)

Logic that decides whether a local mask draft should paint, wait for server, or clear is covered by unit tests with table-driven inputs (deferred flag, page busy, page id mismatch).

**Acceptance**: Policy cases covered without a browser.

### User Story 3 - CI runs frontend units (Priority: P1)

GitHub Actions runs the Node frontend unit suite in addition to Python unit tests.

**Acceptance**: Workflow contains a frontend job; local `node --test` matches.

### User Story 4 - Typesetter pivot/rotation unit gap shrinks (Priority: P2)

Rotation around an explicit pivot changes layer geometry as expected in a Python unit test (inventory 14 partial).

**Acceptance**: New or extended typesetter unit asserts pivot rotation behavior.

## Requirements

- **FR-001**: Shared JS helpers for mask stroke painting MUST be unit-tested under Node.
- **FR-002**: Mask-draft keep/clear/wait policy MUST be unit-tested.
- **FR-003**: CI MUST run frontend unit tests on push/PR to main.
- **FR-004**: Typesetter rotation-with-pivot MUST have a focused Python unit test.
- **FR-005**: Flutter out of scope.

## Success Criteria

- **SC-001**: `node --test tests/js` passes locally.
- **SC-002**: CI workflow includes frontend job.
- **SC-003**: Typesetter pivot rotation unit passes.
- **SC-004**: Inventory 23 addressed; 14 partially addressed.

## Assumptions

- No new heavy frontend framework; Node built-in test runner is enough.
- Full visual e2e for mesh handles remains optional beyond existing Python mesh/layout tests.
