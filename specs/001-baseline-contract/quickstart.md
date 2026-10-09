# Quickstart Validation: Baseline Product Contract

## Prerequisites

- Python environment with project dependencies installed
- Optional vision LLM server for the preferred path; offline fallbacks must still be testable without it
- For extension checks: built `dist/chromium` or `dist/firefox` and remote listener enabled

## Scenario A — CLI page (US1)

1. Run command-line translation on one page image to an output path.
2. Confirm a result image exists.
3. Repeat with LLM URL pointing at an unreachable server and confirm the run completes with a fallback warning.

## Scenario B — Window project (US2)

1. Start `python -m src.app`.
2. Add files or a folder; confirm pages appear.
3. Translate one page; confirm status reaches done/offline/error visibly.
4. Set an API key through the secret control; confirm settings JSON on disk has no key field value.
5. Export at least one result image.

## Scenario C — Extension + remote (US3, US4)

1. Start with remote access enabled.
2. Pair extension using a fresh six-digit code.
3. Hover a qualifying large image for two seconds; confirm compact control appears.
4. Translate; confirm substituted result and original toggle.
5. With remote disabled, confirm unpaired clients cannot submit remote translate jobs through the local UI port.

## Scenario D — Quality claims (FR-013 / SC-008)

1. Inspect README and related docs for ink-recall statements.
2. Confirm each statement points at local reference evidence and does not promise arbitrary-page quality.
