# Contract: Deferred edits (client)

## editDocument options

- `deferApply: true` — enter/keep deferred session; no save.
- Sticky: if `state.deferredApply` already true, behave as deferred even without the flag.
- `coalesce` — only for continuous field gestures (e.g. `font:id`), never a shared `"stroke"` key across strokes.

## commitDeferredEdits

- Clears deferred flag + baseline; schedules immediate save/typeset of pending body.

## undo / redo

- While `contentKey(document) !== deferredBaselineKey`: update local document + pendingBody only.
- When equal to baseline: `deferredApply=false`, clear baseline; may scheduleSave if leaving deferred with committed equality (typically no-op content).
