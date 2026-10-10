# Research: Deferred Style Edits & Stepwise Undo

## Decision: One undo step per completed stroke

**Rationale**: Editors (tldraw marks, Excalidraw history, canvas stroke stacks) batch *within* a gesture, not across gestures. Here each pointer-up is one gesture. Shared `coalesce: "stroke"` incorrectly merges all strokes into one undo entry.

**Alternatives considered**: Keep coalesce and mark boundaries on pointer-up — unnecessary when each editDocument already happens once per stroke.

## Decision: Sticky deferred session + baseline key

**Rationale**: Style edits must not `scheduleSave` or clear `deferredApply`. While any draft is open, later edits (including box moves) stay local until Done. Compare `contentKey(document)` to baseline to know if Done is still needed after undo.

**Alternatives considered**: Separate defer flags for mask vs style — more UI complexity, rejected by scope.

## Decision: Inspector fields use deferApply

**Rationale**: User asked for right-panel style to wait for Done. Same gate as mask.

## References

- tldraw history marks / batching per interaction
- Excalidraw HistoryDelta stacks
- Prior bug class: deferred snapshots firing with same post-mutation state (coalesce/async)
