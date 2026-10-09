# Data Model notes

No new persisted entities.

Transient UI:

- **detailsOpen**: map `regionId → { warp?: boolean, styles?: boolean }` only for the duration of a rebuild (captured from DOM, applied to new markup).
- **deferredApply** / **maskDraft**: already in `state.js` / `viewer.js`.
