# Research: Fix Contract Gaps

## Decision 1: Balloon text is always dialogue on geometry fallback

**Decision**: In `RapidOcr._guess_type`, if `bubble_bbox is not None`, set `block_type = "dialogue"` unconditionally. Do not use short-CAPS → `sfx`.

**Rationale**: Geometry fallback cannot tell stylized SFX inside a balloon from shouted speech. False `sfx` drops translation under default skip; false `dialogue` on rare in-balloon SFX is recoverable by the user. Matches FR-001/FR-002.

**Alternatives considered**: Keep CAPS≤12 → sfx inside balloon (current bug); require VLM-only for balloon types (offline path would stay broken).

## Decision 2: Vision prompt forbids sfx for balloon speech

**Decision**: Tighten the VLM type instruction so speech/thought inside a balloon is `dialogue` even when ALL CAPS; `sfx` is for sound effects / stylized onomatopoeia not ordinary balloon speech.

**Rationale**: Prompt currently lists CAPS examples under `sfx` without excluding balloons, which encourages dialogue→sfx.

**Alternatives considered**: Post-process VLM types by forcing dialogue when `bubble_bbox` set (also viable; do both for belt-and-suspenders if crop returns sfx — prefer prompt first, add post-clamp if tests show need).

## Decision 3: Short free-text → sign

**Decision**: Outside balloons: shout → `sfx`; else if short alphabetic text (≤12 chars after strip, or ≤3 words and ≤24 chars) → `sign`; else → `narration`.

**Rationale**: Offline path never emitted `sign`, so object labels became narration and were translated. Heuristic aligns with existing `sign` in `BLOCK_TYPES` / `TRANSLATABLE_TYPES` exclusion.

**Alternatives considered**: Always `sign` for free text (breaks captions); ML classifier (out of scope); length-only without shout branch (breaks free-text SFX).

## Decision 4: LaMa ring excludes ink from background sample

**Decision**: In `_fill_if_uniform`, detect high-contrast ring pixels relative to median; exclude them from uniformity/color stats; require enough remaining background samples. Optionally use a slightly smaller dilate for the ring so neighbors enter less often. Prefer flat fill when background is clean so LaMa is not invoked with a dilated mask that swallows neighbors.

**Rationale**: Constitution trap: LaMa redraws letters when the uniformity ring captures neighbor text and flat fill fails. Excluding ink restores flat fill on clean pages with nearby glyphs.

**Alternatives considered**: Blindly return False when any ink in ring (forces LaMa — worse); only shrink dilate (helps but incomplete); change LaMa dilate API (out of scope).

## Decision 5: PROBLEMS hygiene only for confirmed-stale items

**Decision**: Remove sections on large extension button, instant hover, every img>180px; remove dialogue→sfx after code fix. Leave Flutter and other wishlist untouched.

**Rationale**: Extension verification already PASS; list must match reality.
