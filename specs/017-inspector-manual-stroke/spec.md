# Feature Specification: Stable Inspector, Manual Translation, Stroke Width

**Feature Branch**: `017-inspector-manual-stroke`

**Created**: 2026-10-10

**Status**: Draft

**Input**: Stabilize right inspector against re-renders; protect manual translations from LLM overwrite; add stroke width in region styles.

## User Scenarios & Testing

### User Story 1 - Inspector menus stay open (Priority: P1)

While a page job progresses or unrelated state ticks, the user can open font `<select>` and style `<details>` without them closing mid-interaction.

### User Story 2 - Manual translation wins (Priority: P1)

User types a translation; later LLM/VLM apply does not overwrite it. Typeset uses the manual text.

### User Story 3 - Stroke thickness (Priority: P2)

User sets per-region stroke width in the style block; typeset uses that width in custom stroke mode.

## Requirements

- **FR-001**: Inspector MUST NOT wipe region list DOM when content fingerprint is unchanged.
- **FR-002**: Open details across cards MUST be restored when a rebuild is required.
- **FR-003**: Manual translation edits MUST set `translation_locked`; machine translators MUST skip locked translations.
- **FR-004**: Inspector MUST expose `stroke_width` for the selected region style.
