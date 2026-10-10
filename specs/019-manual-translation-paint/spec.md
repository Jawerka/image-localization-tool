# Feature Specification: Manual Translation Autosave + Paint

**Feature Branch**: `019-manual-translation-paint`

**Created**: 2026-10-10

**Status**: Draft

**Input**: Manual translation must autosave (not wait for Done) and always paint in the box even when OCR/VLM failed or original text is empty.

## User Scenarios & Testing

### User Story 1 - Translation autosaves (Priority: P1)

User types in «Перевод» or «Оригинал»; after debounce the document is saved without pressing «Готово». Style/mask edits still use Done.

### User Story 2 - Manual text paints after OCR error (Priority: P1)

Region has empty or failed OCR original; user enters a translation; after save the typeset result shows that text in the frame (unless skip).

## Requirements

- **FR-001**: Inspector `text` and `translation` edits MUST flush with debounce (`deferApply: false` unless a deferred mask/style session is already open).
- **FR-002**: Apply/typeset MUST draw any non-empty `translation` when `skip` is false, without requiring non-empty `text` or a translatable `block_type`.
- **FR-003**: `translation_locked` behavior from 017 MUST remain unchanged.
