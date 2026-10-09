# Implementation Plan: Fix Contract Gaps

**Branch**: `002-fix-contract-gaps` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-fix-contract-gaps/spec.md`

## Summary

Close three confirmed baseline gaps: balloon speech must stay `dialogue` (not `sfx`), offline free-text short labels must become `sign` (not always `narration`), and LaMa flat-fill must not treat neighboring ink as clean background. Refresh `docs/PROBLEMS.md` for stale extension bullets and the dialogue→sfx entry after the fix. Touch only `vlm_ocr.py`, `rapid_ocr.py`, `lama_inpainter.py`, `PROBLEMS.md`, and focused unit tests.

## Technical Context

**Language/Version**: Python 3.10–3.13

**Primary Dependencies**: Existing OCR/LaMa stack (PIL, OpenCV, numpy); no new packages

**Storage**: N/A (in-memory region types and image arrays)

**Testing**: pytest under `tests/unit/`

**Target Platform**: Local CLI / desktop app pipeline (Windows + LAN container unchanged)

**Project Type**: Desktop/CLI image localization tool

**Performance Goals**: No measurable regression on page pipeline; classification is O(regions)

**Constraints**: Minimal diff; no new engine file; no new Config fields; Russian comments/docstrings; default `sfx` skip unchanged

**Scale/Scope**: Four user stories; three source files + PROBLEMS + tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status |
|------|--------|
| I. Pipeline v2 only | PASS — no alternate page path |
| II. Minimal diff / no new engine / no new Config | PASS — edits in existing components |
| III. Russian comments/docstrings | PASS — any new notes in Russian |
| IV. Local data not committed | PASS — no models/config |
| V. Quality claims reference-only | PASS — no new ink-recall claims |
| Compatibility surfaces | PASS — CLI/app/extension contracts unchanged |
| Known trap: LaMa ring | ADDRESSED — US3 / FR-007 |

Post-design: unchanged — still PASS.

## Project Structure

### Documentation (this feature)

```text
specs/002-fix-contract-gaps/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── classification-cleaning.md
└── tasks.md
```

### Source Code (repository root)

```text
src/components/vlm_ocr.py
src/components/rapid_ocr.py
src/components/lama_inpainter.py
docs/PROBLEMS.md
tests/unit/test_rapid_ocr_guess_type.py   # new
tests/unit/test_vlm_ocr.py                # prompt assertion
tests/unit/test_lama_inpainter.py         # neighbor-ink case
specs/001-baseline-contract/tasks.md      # mark T030–T032 done after converge
```

**Structure Decision**: Single-project layout; surgical edits in existing OCR and inpaint modules.

## Complexity Tracking

No constitution violations. No unjustified complexity.
