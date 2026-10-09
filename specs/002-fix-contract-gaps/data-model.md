# Data Model: Fix Contract Gaps

No new entities. Existing `TextRegion` fields involved:

| Field | Role in this feature |
|-------|----------------------|
| `bubble_bbox` | Present → balloon speech; geometry fallback forces `dialogue` |
| `block_type` | Values: `dialogue`, `narration`, `title`, `sfx`, `sign`, `noise` |
| `text` | Input to shout / length heuristics |

Translation selection (`should_translate`):

- Translatable by default: `dialogue`, `narration`, `title`
- Skipped by default: `sign`, `noise`, `sfx` (unless `translate_sfx`)

Inpaint:

- Mask component + uniformity ring (dilated component minus full mask) → flat fill color or LaMa path
- Ring ink outliers excluded from background sample
