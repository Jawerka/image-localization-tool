# Feature Specification: Fix Contract Gaps

**Feature Branch**: `002-fix-contract-gaps`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Закрыть подтверждённые пробелы baseline-контракта: диалог в облачке не sfx, RapidOCR free-text→sign, кольцо LaMa без захвата соседнего текста; убрать устаревшие пункты про кнопку расширения из PROBLEMS.md. Flutter и прочий wishlist вне скоупа."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Speech in a balloon stays dialogue (Priority: P1)

A reader translates a comic page with default sound-effect skipping. Speech or thought inside a balloon must be treated as dialogue and translated. Short ALL-CAPS lines inside a balloon must not be treated as sound effects just because they are short and uppercase.

**Why this priority**: Misclassified speech is skipped by default and never appears in the result — the highest functional breakage among the confirmed gaps.

**Independent Test**: Classify sample balloon regions (including short CAPS) and confirm they are dialogue; confirm true free-text shout remains a sound effect; with default skip, dialogue is translated and sound effects are not.

**Acceptance Scenarios**:

1. **Given** text inside a speech or thought balloon, **When** the page is classified (vision path or offline geometry fallback), **Then** the region type is dialogue, not sound effect.
2. **Given** a short ALL-CAPS line inside a balloon, **When** the offline geometry fallback classifies it, **Then** the type is still dialogue.
3. **Given** a short ALL-CAPS shout outside any balloon, **When** classified offline, **Then** the type may be sound effect and default skip still leaves it untranslated.

---

### User Story 2 - Object labels stay untranslated offline (Priority: P2)

Without a vision model, short labels printed on objects (spines, UI chrome, product marks) must not be classified as narration. Narration is translated by default; object labels must remain skipped like other non-translatable kinds.

**Why this priority**: Offline path currently forces free text into narration, so labels that should stay in the source language get translated.

**Independent Test**: Classify short free-text (no balloon) as an object label; confirm default translation selection excludes it; confirm longer free-text caption still counts as narration.

**Acceptance Scenarios**:

1. **Given** a short free-text string outside a balloon that is not a shout, **When** the offline classifier runs, **Then** the type is an object label (not narration).
2. **Given** default translation rules, **When** selecting regions to translate, **Then** object labels and noise are skipped; dialogue, narration, and titles are included.
3. **Given** a longer free-text caption outside a balloon, **When** classified offline, **Then** the type remains narration and is still translated by default.

---

### User Story 3 - Cleaning does not regrow neighbor letters (Priority: P2)

When the cleaner fills a masked glyph next to other remaining text, the neighborhood used to judge a flat background must not treat neighboring ink as clean fill context in a way that pulls those letters into the cleaned hole.

**Why this priority**: Confirmed constitution trap; ruins otherwise correct masks on dense pages.

**Independent Test**: Mask one dark glyph on a light page with a second unmasked glyph nearby; after clean, the hole is filled with background and the neighbor glyph pixels stay intact without invoking a generative fill when a flat fill is appropriate.

**Acceptance Scenarios**:

1. **Given** a masked text blob and an unmasked neighboring letter close by on a uniform background, **When** flat cleaning runs, **Then** the neighbor letter remains and the hole is filled with background color.
2. **Given** a ring around the mask that contains high-contrast ink from a neighbor, **When** uniformity is judged, **Then** that ink is not treated as part of the clean background sample used for fill.

---

### User Story 4 - Stale extension problems are cleared from the list (Priority: P3)

The living problems list must not keep extension button issues that the current extension already satisfies (large text button, instant hover, every large img). The dialogue-as-sound problem entry is removed only after User Story 1 is fixed.

**Why this priority**: Documentation hygiene so the list matches reality; does not change runtime behavior.

**Independent Test**: Read the problems list; stale extension sections are gone; Flutter and other open items remain; dialogue-as-sound section is gone after the classification fix.

**Acceptance Scenarios**:

1. **Given** the problems document after this feature, **When** a reader looks for the large «Перевести» button, instant hover, or every-img>180px issues, **Then** those sections are absent or marked resolved.
2. **Given** the classification fix from User Story 1 is merged, **When** reading the problems list, **Then** the «Текст в облачке распознаётся как звук» section is absent or marked resolved.
3. **Given** other open wishlist items (Flutter shell, auto-run edits, warp issues, etc.), **When** the document is updated, **Then** those sections remain unchanged.

### Edge Cases

- Empty or non-alphabetic text in a balloon: still dialogue, not sound effect.
- Balloon present but shout heuristic would have fired: dialogue wins.
- Free-text shout of medium length (uppercase, within shout length): sound effect, not object label.
- Neighbor ink far from the mask: existing flat-fill behavior on clean white pages unchanged.
- Extension checklist items already PASS in baseline: no code change in the extension.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Text inside a speech or thought balloon MUST be classified as dialogue, not as a sound effect, on both the vision recognition path and the offline geometry fallback.
- **FR-002**: On the offline geometry fallback, short ALL-CAPS text inside a balloon MUST remain dialogue.
- **FR-003**: Short ALL-CAPS free-text outside a balloon MAY be classified as a sound effect; default skip of sound effects MUST continue to leave them untranslated.
- **FR-004**: On the offline geometry fallback, short non-shout free-text outside a balloon MUST be classified as an object label (`sign`), not as narration.
- **FR-005**: Longer non-shout free-text outside a balloon MUST remain narration and stay translatable by default.
- **FR-006**: Default translation selection MUST continue to include dialogue, narration, and title, and MUST exclude object labels, noise, and sound effects unless the user opts into sound-effect translation.
- **FR-007**: Flat background fill MUST NOT treat high-contrast neighboring ink in the uniformity ring as clean background; neighbor glyphs next to a mask MUST remain after cleaning when a flat fill is used.
- **FR-008**: The living problems list MUST drop or resolve the stale extension-button sections (large text label, instant hover, every large img) and MUST drop or resolve the dialogue-as-sound section after FR-001 is satisfied.
- **FR-009**: This feature MUST NOT change the Flutter wishlist or other unrelated open problems entries.

### Key Entities

- **Text region**: A detected text area with optional balloon bounds, source text, and a type (dialogue, narration, title, sound effect, object label, noise).
- **Translation selection**: The set of regions chosen for translation under default or user sound-effect mode.
- **Uniformity ring**: Neighborhood around a mask component used to decide whether a flat background fill is safe.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a sample of balloon speech lines including short CAPS, 100% are classified as dialogue on the offline fallback; none are sound effects.
- **SC-002**: On a sample of short non-shout object labels without balloons, 100% are classified as object labels on the offline fallback and are excluded from default translation.
- **SC-003**: On a constructed page with a masked glyph beside an unmasked neighbor on uniform background, after cleaning the neighbor glyph retains its ink and the hole shows background fill without generative redraw of the neighbor.
- **SC-004**: After the feature, a reader of the problems list finds zero stale extension-button sections among the three named above, and zero open «dialogue as sound» section once classification is fixed.
- **SC-005**: Default sound-effect skip and default translation of dialogue/narration/title remain unchanged for regions whose types are already correct.

## Assumptions

- Baseline feature `001-baseline-contract` already documents the intended product contract; this feature only closes the three confirmed code gaps plus problems-list hygiene.
- Vision-path improvements are prompt/rule tightening only; no new recognition engine.
- Offline object-label heuristic is geometric/length-based; perfect semantic sign detection is out of scope.
- Extension runtime already matches FR-012/016/013 and Ozon checks from baseline; no extension code changes.
- Auto-commits from Spec Kit git hooks are skipped for this feature unless the user asks to commit.
