# Data Model: Page Editor and Typeset

No new persisted entities. Relevant existing fields:

| Field | Role |
|-------|------|
| `PageDocument.strokes` | Accumulated mask strokes; applying them triggers `clean` plan |
| `page.status` | `done`/`edited`/`running`/… — UI uses ready vs not-ready for result display |
| `TextRegion.style.rotation` / `warp` | First layout must stay 0/`none` for ordinary text |
| Client `deferApply` | Session-only: strokes held until «Готово» without PUT |
