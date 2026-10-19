# Feature Specification: Free-Text Crop OCR + Editable Original

**Feature Branch**: `018-free-ocr-edit`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: VLM free-text page-pass scrambles box ids (warning + crop reread); inspector «Оригинал» is readonly so manual OCR fixes are rejected.

## User Scenarios & Testing

### User Story 1 - Free text OCR without id scramble (Priority: P1)

On a page with multiple free-text (non-balloon) regions, VLM reads each via crop. No warning «VLM перепутал номера рамок (свободный текст)…». Balloon pass stays page-marked + verify.

### User Story 2 - Editable original text (Priority: P1)

User types into «Оригинал» in the inspector; value persists in the document (`region.text`, `edited`). Translation lock from 017 is unchanged. No auto-retranslate; user may click «Перевести заново».

## Requirements

- **FR-001**: Free-text regions (no `bubble_bbox`) MUST be OCR'd via per-region crop, not a numbered page-pass.
- **FR-002**: Balloon regions MUST keep the existing page-pass + verify path.
- **FR-003**: Inspector «Оригинал» MUST be editable and write `region.text` with `edited=true`.
- **FR-004**: Editing original MUST NOT clear or set `translation_locked`.
