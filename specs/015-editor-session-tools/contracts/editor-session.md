# Contract: editor session

## POST /api/project/package/save

Body may include `editor: { active_page_id, zoom, scroll_left, scroll_top }`.
Response includes the same `editor` (echoed from pack).

## Package project.json

Optional `editor` object as above. Older packages without it remain valid.

## MaskStroke

`mode` ∈ `paint` | `erase` | `fill` | `erase_fill`.
