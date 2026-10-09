# Implementation Plan: Baseline Product Contract

**Branch**: `001-baseline-contract` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-baseline-contract/spec.md`

**Note**: This plan maps the published product contract onto the existing repository layout. It does not propose new engines, settings, or surfaces. Work produced from this plan is verification and gap recording, not product rewrite.

## Summary

Capture and verify the already-promised behaviour of CLI translation, desktop window projects, browser extension pairing, and optional LAN access against the shared page-processing path. Reuse the current module boundaries; record gaps instead of inventing alternate architecture.

## Technical Context

**Language/Version**: Python 3.10–3.13

**Primary Dependencies**: Existing project stack for detection, OCR, translation, inpainting, desktop HTTP UI, and browser extension (no new dependencies for this baseline)

**Storage**: Local files for projects, settings, logs, models, and session token; API key in OS keyring for the window

**Testing**: Existing pytest suite plus manual contract checks from `quickstart.md`

**Target Platform**: Windows desktop primary; LAN clients via browser extension; CLI usable wherever the Python environment runs

**Project Type**: Desktop application with CLI, local HTTP UI, optional LAN API, and browser extension

**Performance Goals**: Complete a single-page translation end-to-end; remote queue stays within documented unfinished-job and rate limits

**Constraints**: Single shared page-processing path; local UI on loopback; remote listener opt-in; no API key in settings JSON; reference ink-recall figures must stay reference-only

**Scale/Scope**: Four user stories covering CLI, window, extension, and access boundary; verification of eighteen functional requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Пайплайн v2**: Plan keeps all translation surfaces on the existing shared page-processing entry. Pass.
- **Минимальный diff**: Plan adds specification artefacts and verification tasks only; no new engines or Config fields. Pass.
- **Русский язык**: New comments or docstrings introduced later for remediation MUST stay Russian; this plan itself is process English for Spec Kit templates. Pass for scope.
- **Локальные данные**: Plan forbids committing models, config, test images, data, output, or secrets. Pass.
- **Заявленное качество**: Plan and spec require reference-only wording for ink recall. Pass.
- **Границы совместимости**: CLI, window, extension, and LAN remain; plan does not remove or replace them. Pass.
- **Известные ловушки**: Verification tasks MUST check RT-DETR size order, single-request LLM handling, and LaMa homogeneity ring behaviour where relevant. Pass with explicit checks below.

Post-design re-check: unchanged. No complexity exceptions required.

## Project Structure

### Documentation (this feature)

```text
specs/001-baseline-contract/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
├── checklists/
└── tasks.md
```

### Source Code (repository root)

```text
src/
├── main.py
├── page_pipeline.py
├── config.py
├── models.py
├── app/                 # window, local HTTP, LAN, worker
└── components/          # detector, OCR, translate, mask, inpaint, typeset
web/                     # window UI
extension/               # browser extension sources
scripts/                 # setup_models, eval_pipeline, builds
docs/                    # APP, EXTENSION, BENCHMARK_RESULTS
tests/
```

**Structure Decision**: Keep the existing single-repo layout. Baseline verification maps requirements onto these paths and does not add packages.

## Complexity Tracking

> No constitution violations require justification.
