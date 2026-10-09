# Contract: Classification and Cleaning Gaps

## Offline geometry type guess (`RapidOcr._guess_type`)

| Input | Output `block_type` |
|-------|---------------------|
| `bubble_bbox` set (any text, including short CAPS) | `dialogue` |
| no balloon, shout (all letters upper, len ≤ 24) | `sfx` |
| no balloon, not shout, short label heuristic | `sign` |
| no balloon, not shout, longer text | `narration` |

## Vision OCR type rules

- Balloon speech/thought → `dialogue` (even ALL CAPS).
- `sfx` → onomatopoeia / stylized sound effects, not ordinary balloon lines.
- `sign` → text printed on objects.
- Default translation set unchanged: dialogue/narration/title only.

## Flat fill uniformity

- Ring = dilate(component) minus full mask.
- High-contrast ink in ring is excluded from background median/std.
- If enough clean background samples remain and they are uniform → flat fill; neighbor ink pixels outside the component stay unchanged.
- Inpaint public API (`inpaint(...)`) unchanged.
