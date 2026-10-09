# Research: Editor Harden + Done/Mask E2E

## Decision: Snapshot details open, not full DOM patch

**Rationale**: Full incremental DOM is out of scope (FR). Existing rebuild already restores focus/scroll; mirroring glossary-panel's capture/restore for `<details open>` is enough for C11.

**Alternatives**: Morphdom / virtual list — rejected as oversized for this debt item.

## Decision: Default open only when no snapshot

**Rationale**: Current cards hardcode `open` so first selection shows warp controls. After user toggles, snapshot wins. Fresh select of another region has no snapshot → default open for warp; styles details open only when library non-empty (current).

## Decision: E2E via FakeWorker desktop fixture

**Rationale**: Same harness as `test_ui_smoke.py`. Brush uses pointer events on stage; assert `[data-role='mask-local']` visibility / `frame--mask-draft` and `[data-role='apply-edits']`.

**Note**: Server mask may lag; test asserts local draft before Готово and deferred UI clear after.
