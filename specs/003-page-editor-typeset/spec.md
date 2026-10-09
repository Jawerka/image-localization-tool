# Feature Specification: Page Editor and Typeset

**Feature Branch**: `003-page-editor-typeset`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Page editor and typesetting debt from PROBLEMS.md excluding Flutter shell: keep result during re-layout, Done for accumulated edits, blue brush preview, first layout without rotation/warp for ordinary text, rotation about text-field center, balloon fill and short-reply sizing, warp labels and mesh, style on block card, small-page scale; verify prior SFX/reset-style fixes. Flutter shell out of scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep the finished page visible while re-layout runs (Priority: P1)

A user has a finished translated page on screen. They edit the mask with brush or eraser (or otherwise trigger a new layout). While the new layout is running, the previous finished image stays visible. When the new layout finishes, it replaces the old image in place. The user never sees an empty hole where the page was.

**Why this priority**: Losing the result mid-edit breaks trust in the editor and makes fine mask work painful.

**Independent Test**: Produce a finished page, start a re-layout that takes noticeable time, and confirm the prior result remains visible until the new one appears.

**Acceptance Scenarios**:

1. **Given** a page with a finished result showing, **When** a re-layout starts after a mask edit, **Then** the previous result remains visible for the whole run.
2. **Given** a re-layout that completes successfully, **When** the new result is ready, **Then** it replaces the previous image without an intermediate blank page area.

---

### User Story 2 - Confirm edits with Done instead of auto-running every stroke (Priority: P1)

A user makes several brush or eraser strokes while refining a page. Individual strokes do not each enqueue a full processing run. When the user is finished refining, they press an explicit control such as «Готово». Only then does the product apply the accumulated edits and run processing.

**Why this priority**: Auto-run on every stroke wastes time and starts work before the edit is finished.

**Independent Test**: Apply multiple strokes without pressing Done and confirm no full run is queued; press Done and confirm one run that reflects all accumulated edits.

**Acceptance Scenarios**:

1. **Given** the page editor with brush or eraser active, **When** the user draws one or more strokes, **Then** those strokes alone do not enqueue a full page run.
2. **Given** accumulated uncommitted edits, **When** the user activates «Готово» (or equivalent confirm control), **Then** one run starts that accounts for those edits.
3. **Given** no pending edits, **When** the user looks at the confirm control, **Then** it is clear that confirmation applies accumulated changes (disabled or inert when there is nothing to apply is acceptable).

---

### User Story 3 - See a blue translucent stroke preview (Priority: P2)

While drawing with brush or eraser, the live stroke preview is blue and translucent so both the stroke path and the artwork under it remain visible. The preview color does not change the actual retouch result on the page.

**Why this priority**: White preview is nearly invisible on light art and confuses retouch on dark art.

**Independent Test**: Draw on light and dark regions and confirm the preview is blue and translucent; confirm the committed retouch is unaffected by the preview tint.

**Acceptance Scenarios**:

1. **Given** brush or eraser mode, **When** the user draws a stroke, **Then** the on-page preview stroke is blue and semi-transparent.
2. **Given** a completed stroke that commits retouch, **When** the page updates, **Then** the retouch itself is not forced to the preview blue solely because of the preview style.

---

### User Story 4 - First layout of ordinary text stays upright (Priority: P2)

On the first automatic layout of an ordinary text block (not a sound-effect block), the product does not copy ink-derived rotation or warp into the style. The first layout is straight: no rotation and no warp. Ink-derived fill and stroke remain allowed. Sound-effect first layout that already avoids copying angle and arc stays correct (see Verification stories).

**Why this priority**: Vertical source columns currently tilt target-language text and hurt readability.

**Independent Test**: Run first layout on an ordinary balloon or free-text region from a vertical source column and confirm rotation is zero and warp is none.

**Acceptance Scenarios**:

1. **Given** an ordinary text region receiving its first automatic layout, **When** style is assigned from ink, **Then** rotation is zero and warp kind is none.
2. **Given** the same region, **When** fill and stroke are taken from ink, **Then** those color attributes may still be applied.
3. **Given** the user later sets rotation or warp manually, **When** they save that choice, **Then** the manual values are kept for subsequent layouts until cleared.

---

### User Story 5 - Rotate around the text field center (Priority: P2)

When the user rotates a block, the frame stays put and only the writing direction changes. Rotation is measured and applied around the center of the text field, so the block does not jump and need re-positioning after each angle change.

**Why this priority**: Mismatched pivot between handle and drawn glyphs makes placement tedious.

**Independent Test**: Rotate a selected block with the on-page handle and confirm the frame center stays fixed while glyphs reorient.

**Acceptance Scenarios**:

1. **Given** a selected text block with a visible frame, **When** the user changes rotation via the page handle, **Then** the frame center remains in place and only orientation changes.
2. **Given** the same block, **When** comparing handle measurement and applied rotation, **Then** both use the text-field center as the shared pivot.

---

### User Story 6 - Fit balloon text and tame short replies (Priority: P2)

Translated text in a speech balloon uses the same usable interior that retouch already cleans, approaching the balloon edge within about two to three pixels so type can be larger and less empty. Short replies such as «А», «Да», «Угу», or «Но» do not inflate to the maximum size that fits the balloon; they take a size consistent with nearby balloons so the page reads at one scale.

**Why this priority**: Large empty margins and giant one-word balloons look broken next to dense neighbors.

**Independent Test**: Compare a long balloon line for edge closeness after layout; compare a one-word balloon’s size to neighboring balloons of normal dialogue.

**Acceptance Scenarios**:

1. **Given** a speech balloon with a finished translation layout, **When** measuring margin from glyphs to the usable balloon interior, **Then** the gap is on the order of two to three pixels rather than a large fraction of the short side.
2. **Given** a very short reply in a large balloon beside normal dialogue balloons, **When** automatic size is chosen, **Then** the short reply’s size aligns with nearby balloons instead of filling the balloon height.

---

### User Story 7 - Warp controls match their names and mesh bends text (Priority: P3)

Warp mode labels describe the visible deformation. Arc bends the line as a vertical bow (not a sideways slide only). Ring, wave, and related presets behave as their names imply, with control ranges that produce predictable motion. Choosing mesh creates and drives control points so dragging them visibly bends the text; mesh is not a no-op and does not throw glyphs far off the frame from coordinate mismatch.

**Why this priority**: Misnamed warps and broken mesh waste expert editing time.

**Independent Test**: Apply each named warp at a moderate amount and compare the result to the label; enable mesh, drag a control point, and confirm text follows.

**Acceptance Scenarios**:

1. **Given** a block with an arc-up or arc-down warp, **When** bend is non-zero, **Then** the line bows in the vertical sense implied by the label rather than only sliding sideways.
2. **Given** wave or flag-style warps, **When** bend is adjusted, **Then** the visible motion matches the distinct intent of those labels (not identical unlabeled behavior).
3. **Given** mesh warp is selected, **When** the user moves a mesh control point, **Then** the laid-out text visibly changes shape according to that move.

---

### User Story 8 - Edit style on the selected block card (Priority: P3)

Frequent style controls—font family, size, fill, and stroke—live on the selected block’s card next to translation controls. The user does not switch to a separate inspector tab for those everyday changes. Font is a compact chooser (opens on demand, with next/previous like size), not a tall always-open list. Warp and project style presets are available without a separate tab trip and are not an always-expanded wall of buttons.

**Why this priority**: Split Text/Style tabs force constant context switching for routine edits.

**Independent Test**: Select a block and change font, size, fill, and stroke without leaving the block card; confirm warp remains reachable without a dedicated Style tab for everyday work.

**Acceptance Scenarios**:

1. **Given** a selected block card, **When** the user changes font, size, fill, or stroke, **Then** those controls are on the card and do not require switching to a separate Style tab.
2. **Given** the font control, **When** the list is closed, **Then** it does not permanently occupy a large vertical strip of the inspector.
3. **Given** warp or project style presets, **When** the user needs them, **Then** they are reachable from the block editing context without a mandatory tab change for basic styling.

---

### User Story 9 - Scale small pages before layout (Priority: P3)

On small page images (for example about 605×850), layout looks less even than on large pages. Before layout, the product scales such images so the long side reaches about 2000 pixels, bringing region scale closer to ordinary pages, then proceeds with detection and layout consistently for that run.

**Why this priority**: Small scans currently produce uneven region sizing relative to normal pages.

**Independent Test**: Run the same content at native small size and confirm the effective layout path uses an upscaled long side near 2000 px for region work (user-visible export policy may keep or map back to original size as later planning decides; this story requires even region scale via upscaling before layout).

**Acceptance Scenarios**:

1. **Given** a page whose long side is well below about 2000 pixels, **When** layout begins, **Then** region detection and layout operate on a version scaled so the long side is about 2000 pixels.
2. **Given** a page already at or above that long-side target, **When** layout begins, **Then** no unnecessary upscale is required for this story.

---

### Verification Story A - Reset rotation and warp from the block card

A one-action control on the expanded block card clears rotation to zero, sets warp kind to none, sets bend to zero, and clears perspective and mesh points, without changing fill, font, or skew. This was attempted on 2026-10-04; this feature treats it as a verification requirement, not a greenfield build, unless convergence finds a regression.

**Independent Test**: Set rotation and warp on a block, use «Сбросить стили», confirm only angle/warp/mesh/perspective reset.

**Acceptance Scenarios**:

1. **Given** a block with non-zero rotation and an active warp with control points, **When** the user activates reset-styles on the card, **Then** rotation is 0, warp is none, bend is 0, and perspective/mesh points are cleared while fill, font, and skew remain.

---

### Verification Story B - Sound-effect first layout stays without ink angle

First automatic layout of a sound-effect region takes fill and stroke from ink but does not copy ink angle or arc. «Подобрать стиль заново» likewise does not restore tilt. Attempted 2026-10-04; verify unless convergence finds a regression.

**Independent Test**: First-layout and restyle a sound-effect region; confirm no rotation/warp from ink.

**Acceptance Scenarios**:

1. **Given** a sound-effect region on first automatic layout or restyle-from-ink, **When** style is applied, **Then** only fill and stroke come from ink for those geometric attributes, not rotation or arc warp.

### Edge Cases

- Re-layout fails or errors: the previous finished image remains visible; the user is not left with a blank page solely because the run failed.
- User draws strokes then switches tools before Done: accumulated edits remain until confirmed or explicitly discarded (discard behavior may be clarified in planning; default is keep until Done).
- No nearby balloons for short-reply sizing: fall back to a conservative size below the balloon-filling maximum rather than the absolute maximum fit.
- Mesh with no user edits yet: selecting mesh must still establish a usable control lattice so subsequent drags work.
- Ordinary text vs sound effect: upright-first-layout applies to ordinary text; sound effects follow Verification Story B.
- Very large pages: small-page upscale does not downscale or otherwise harm already-large pages.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: While a re-layout or reprocess of an already finished page is in progress, the product MUST keep showing the previous finished page image until the new result is ready to display.
- **FR-002**: Brush and eraser strokes MUST NOT each enqueue a full processing run by themselves.
- **FR-003**: The product MUST provide an explicit confirm control (e.g. «Готово») that starts processing for accumulated page edits.
- **FR-004**: Live brush/eraser stroke preview MUST be blue and semi-transparent; preview styling MUST NOT redefine the committed retouch color solely by copying the preview tint.
- **FR-005**: First automatic layout of an ordinary (non–sound-effect) text block MUST set rotation to zero and warp to none; fill and stroke from ink MAY still apply.
- **FR-006**: Block rotation interaction MUST use the text-field center as the shared pivot so the frame does not jump when angle changes.
- **FR-007**: Balloon typesetting MUST use the same usable balloon interior as retouch cleaning, with glyph-to-edge margin on the order of two to three pixels.
- **FR-008**: Automatic sizing for very short balloon replies MUST prefer sizes consistent with nearby balloons rather than the maximum size that fits the balloon.
- **FR-009**: Named warp modes MUST produce deformations consistent with their labels (including true vertical bow for arc-up/arc-down).
- **FR-010**: Mesh warp MUST create usable control points and MUST visibly bend text when those points move.
- **FR-011**: Font, size, fill, and stroke for the selected block MUST be editable from the block card without switching to a separate Style tab; font chooser MUST be compact when closed.
- **FR-012**: Warp and project style presets MUST remain reachable from the block editing context without requiring a separate Style tab for basic styling.
- **FR-013**: Before layout, pages whose long side is substantially below about 2000 pixels MUST be scaled so the long side is about 2000 pixels for detection and layout.
- **FR-014**: The product MUST keep a one-action reset on the block card that clears rotation, warp kind, bend, and perspective/mesh points without changing fill, font, or skew (verify existing behavior).
- **FR-015**: First automatic layout and restyle-from-ink for sound-effect blocks MUST NOT copy ink rotation or arc into style (verify existing behavior).
- **FR-016**: This feature MUST NOT replace the desktop shell with Flutter; WebView2 (or current shell) remains until a separate Flutter feature.

### Key Entities

- **Page result view**: The on-screen finished or in-progress page image the user judges and edits against.
- **Accumulated edit set**: Mask or related changes held until the user confirms with Done.
- **Text block style**: Rotation, warp, fill, stroke, font, and size applied to a region.
- **Balloon interior**: The usable area inside a speech balloon shared by cleaning and typesetting.
- **Warp mode**: Named deformation (none, arc, ring, wave/flag, mesh, perspective) with user-facing labels.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 10 consecutive re-layout trials after a finished result exists, the previous image remains visible in 100% of trials until the new result appears (zero blank-page flashes).
- **SC-002**: A sequence of at least three brush strokes without Done enqueues zero full runs; one Done after those strokes enqueues exactly one run that reflects all strokes.
- **SC-003**: On light and dark artwork samples, users can distinguish the live stroke path from the underlying art in a quick glance test (preview contrast from blue translucency).
- **SC-004**: On a vertical-source sample page, 100% of ordinary text blocks on first automatic layout have zero rotation and no warp.
- **SC-005**: Rotating a block via the page handle leaves the frame center within a small visual tolerance (no need to re-drag the block to recover position after a typical angle change).
- **SC-006**: On sample balloons, average glyph-to-interior margin after layout is about 2–3 px, and short one-word balloons are not sized at the balloon-filling maximum when neighbors exist.
- **SC-007**: Reviewers can match each named warp to its on-page effect without reading internal mode ids; mesh drag produces a visible bend on a test block.
- **SC-008**: Changing font, size, fill, and stroke for a selected block is possible without leaving the block card in a timed walkthrough.
- **SC-009**: A sample page near 605×850 is laid out using an effective long side of about 2000 px for region work.
- **SC-010**: Verification stories A and B pass on current builds, or gaps are recorded for implementation rather than silently assumed fixed.

## Assumptions

- Source of open issues is the living problems list; Flutter shell migration (Argos-shell theme and mockups) is deferred to a later feature and is out of scope here.
- Baseline product contract (`001-baseline-contract`) and classification/cleaning fixes (`002-fix-contract-gaps`) remain in force; this feature does not reopen CLI, extension, or LAN contracts.
- Desktop editing remains on the current WebView2-based window for this feature.
- «Готово» is the working name for the confirm control; exact label copy may be refined in planning.
- Export/display size after small-page upscale (keep upscaled vs map back to original pixel size) is left to implementation planning with a default of preserving a coherent exported page for the user without surprising resolution jumps—planning must pick one rule and document it.
- Sound-effect upright-first behavior and reset-styles control are treated as already attempted; specify records them as verification, not duplicate invention.
- Command-line-only runs without the interactive editor are unaffected by Done/preview UI stories except where shared layout rules (first layout, balloon fit, short reply, small-page scale, warps) apply.
