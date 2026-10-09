# Feature Specification: Style Card Polish

**Feature Branch**: `004-style-card-polish`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Style card polish from PROBLEMS: project style presets on the region card, font names shown in their own typeface in the font chooser, distinct flag vs wave warp geometry. Remove dead styleLibrary-only load. Flutter shell out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Apply a project style from the block card (Priority: P1)

A user has saved project styles. On the selected block card they see compact chips or buttons for those styles and can apply one without opening a Style tab. Applying updates the block’s style fields (font, fill, stroke, warp as stored). If the library is empty, the card does not pretend presets exist.

**Why this priority**: Presets were lost when the Style tab was removed; this is the remaining FR-012 hole.

**Independent Test**: Seed two project styles, open a region card, click a chip, confirm region style matches the preset.

**Acceptance Scenarios**:

1. **Given** a project with at least one named style, **When** the user opens a selected region card, **Then** those styles are reachable on the card without a Style tab.
2. **Given** a style chip on the card, **When** the user activates it, **Then** the region style updates from that preset and stays on the Text tab context.
3. **Given** an empty style library, **When** the user views the card, **Then** there is no broken empty control wall; loading without UI is not left as a silent dead fetch-only path.

---

### User Story 2 - Recognize fonts by their typeface (Priority: P2)

In the font family control on the block card, each font option is rendered using that font’s typeface (or an equivalent visual preview), so the user can pick by eye.

**Why this priority**: Plain system UI font makes families hard to distinguish.

**Independent Test**: Open the font control with multiple fonts loaded and confirm options use distinct face rendering.

**Acceptance Scenarios**:

1. **Given** fonts returned by the font list API, **When** the user opens the font chooser on the card, **Then** option labels appear in each font’s own face (via `@font-face` or equivalent).
2. **Given** a font that fails to load, **When** the chooser renders, **Then** other fonts still work and the broken face falls back safely.

---

### User Story 3 - Flag and wave look different (Priority: P2)

Choosing «Флаг» produces a different deformation than «Волна». Flag is a one-axis flag-like bow; wave remains the bi-axial sine. Both remain reachable from the card warp presets.

**Why this priority**: Labels currently lie; both map to `wave` with different bend only.

**Independent Test**: Warp the same layer with flag and wave at comparable bend; maps or pixels differ; unit test covers remap difference.

**Acceptance Scenarios**:

1. **Given** warp preset «Волна», **When** applied, **Then** kind is `wave` with bi-axial sine behavior.
2. **Given** warp preset «Флаг», **When** applied, **Then** kind is `flag` (not `wave`) with one-axis flag-like behavior distinct from wave.
3. **Given** bend 0 for either kind, **When** warped, **Then** output matches identity within tolerance.

---

### Edge Cases

- Project with many styles: chips stay compact (wrap or scroll), not a full-height radio wall.
- Applying a preset does not require switching tabs.
- Unknown warp kind from old documents remains harmless (no crash; treated as none or passthrough).
- Flutter shell is out of scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Project style presets MUST be applicable from the selected region card without a separate Style tab.
- **FR-002**: Font chooser options on the card MUST render using each font’s typeface when the face can be loaded.
- **FR-003**: Warp preset «Флаг» MUST use a distinct geometry from «Волна» (`flag` vs `wave`).
- **FR-004**: The product MUST NOT leave a dead `projectStyles` fetch with no UI if presets are in scope; either wire UI or remove the fetch.
- **FR-005**: This feature MUST NOT replace the desktop shell with Flutter.

### Key Entities

- **Project style**: `{ name, style }` stored in the project.
- **Warp kind**: includes `wave` and `flag` as separate kinds.

## Success Criteria *(mandatory)*

- **SC-001**: Timed walkthrough: apply a project style without leaving the Text/region card context.
- **SC-002**: Reviewers can tell font options apart by typeface in the chooser.
- **SC-003**: Unit or visual check shows flag≠wave remap for nonzero bend.
- **SC-004**: PROBLEMS entries for presets, font-face, and wave/flag can be cleared after verify (Flutter remains).

## Assumptions

- Font file serving or equivalent preview mechanism may be added if missing.
- Empty style library is valid; UI stays quiet.
- Saving new styles into the library may remain as today if already possible elsewhere; this feature focuses on apply-from-card.
