# Feature Specification: Fallback Warnings Visibility

**Feature Branch**: `007-fallback-warnings`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Tech-debt B8: when the pipeline silently falls back (VLM→RapidOCR, LLM→Argos, LaMa→OpenCV), the page must carry clear warnings and the UI must surface them without requiring the user to dig for quality loss. OCR/Argos offline status already exists; close the LaMa gap and promote warnings to a visible banner. Flutter out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - OpenCV cleanup fallback is recorded (Priority: P1)

When LaMa fails mid-clean and OpenCV is used instead, the page document includes a human-readable warning that cleanup used OpenCV because LaMa failed. Intentional OpenCV-only settings need not shout like a failure, but unexpected fallback must not stay log-only.

**Why this priority**: LaMa→OpenCV today only logs; status can still look fully successful.

**Independent Test**: Force LaMa crop to raise; assert inpaint result still returns an image and a warning list mentions OpenCV/LaMa.

**Acceptance Scenarios**:

1. **Given** LaMa raises during a window that needs neural clean, **When** OpenCV fallback runs, **Then** a warning is collected on the inpainter and forwarded into page `warnings`.
2. **Given** cleanup succeeds via LaMa, **When** the page finishes, **Then** no OpenCV-fallback warning is invented.

---

### User Story 2 - Existing OCR/translate fallbacks stay visible (Priority: P1)

RapidOCR / Argos fallbacks continue to append warnings and keep the existing «без LLM» / offline page status behavior. No regression.

**Why this priority**: Already partially done; must not break.

**Independent Test**: Existing unit coverage / smoke that warnings include RapidOCR or Argos still pass; offline status still keyed off those strings.

**Acceptance Scenarios**:

1. **Given** LLM/OCR unavailable with LLM backends selected, **When** the page finishes, **Then** warnings mention the fallback and status can be offline as today.
2. **Given** OpenCV-only cleanup fallback without OCR/Argos text, **When** status is computed, **Then** the page is not mislabeled solely as «без LLM» solely because of OpenCV (warnings still present).

---

### User Story 3 - User sees a banner when the active page has pipeline warnings (Priority: P1)

After a page finishes or is reloaded into the editor, if the document has warnings, a warning-tone banner summarizes them so the user does not need to open the Page tab first.

**Why this priority**: Warnings on the Page tab alone hide degradation.

**Independent Test**: Apply detail with document.warnings → banner text contains a warning; empty warnings clear or omit the pipeline banner.

**Acceptance Scenarios**:

1. **Given** the active page document has one or more warnings, **When** detail is applied, **Then** a banner shows those warnings.
2. **Given** a document with no warnings, **When** detail is applied, **Then** the pipeline-warnings banner is not shown.

---

### Edge Cases

- Duplicate warning strings are not repeated endlessly in the banner.
- Very long warning lists may be joined compactly (separator), not a modal wall.
- Flutter out of scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Unexpected LaMa→OpenCV fallback MUST append a clear warning into the page warning list.
- **FR-002**: OCR RapidOCR and translator Argos fallbacks MUST continue to record warnings (no regression).
- **FR-003**: OpenCV-only fallback MUST NOT force the «без LLM» offline status by itself.
- **FR-004**: When the active page document has warnings, the UI MUST show a warning banner summarizing them.
- **FR-005**: This feature MUST NOT replace the desktop shell with Flutter.

### Key Entities

- **Page warnings**: string list on the page document.
- **Pipeline banner**: transient UI notice keyed to those warnings.

## Success Criteria *(mandatory)*

- **SC-001**: Unit test proves LaMa failure yields an OpenCV fallback warning.
- **SC-002**: Offline status remains tied to OCR/Argos-style warnings, not OpenCV alone.
- **SC-003**: Applying a warned document surfaces a banner in the UI layer (testable via state/banner helper or e2e if cheap).

## Assumptions

- Page tab warn-lines remain; banner is additive.
- Full «vs etalon quality report» is out of scope.
