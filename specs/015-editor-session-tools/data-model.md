# Data Model

## EditorSession (in project.json)

| Field | Type | Meaning |
| --- | --- | --- |
| `active_page_id` | string | Last active page id |
| `zoom` | `"fit"` \| `"fit-width"` \| number | Zoom mode or scale |
| `scroll_left` | number | Stage scroll X |
| `scroll_top` | number | Stage scroll Y |

## MaskStroke.mode

Adds `erase_fill`: filled polygon with mask value 0 (subtract).
