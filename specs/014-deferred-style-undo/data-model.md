# Data Model: Deferred Session

## DeferredSession (client state)

| Field | Meaning |
| --- | --- |
| `deferredApply` | True while pending local edits await Done |
| `deferredBaselineKey` | `contentKey` of document when session started (last applied) |
| `document` | Current local page document (strokes + regions) |
| `pendingBody` | Map pageId → body to PUT on commit |
| `history.past` / `future` | Full document snapshots per undo step |

## Transitions

- First deferred edit: set baseline if empty, `deferredApply=true`, no save.
- Undo/redo: pop/push snapshots; `deferredApply = key(doc) !== baseline`; save only if not deferred.
- Done: clear baseline + flag, `scheduleSave(0)`.
- Discard: clear pending, baseline, reload from server.
