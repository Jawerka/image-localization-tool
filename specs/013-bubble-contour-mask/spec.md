# Feature Specification: Bubble Contour Mask

**Feature Branch**: `013-bubble-contour-mask`

**Created**: 2026-10-10

**Status**: Implemented

**Input**: User description: "Dialogue cleanup shows rectangular corners outside the speech bubble and a visible outlined ring inside near the stroke. Improve bubble interior contour so the retouch mask stays inside the real outline and reaches near the inner edge (no large leftover ring)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - No AABB corners outside the bubble (Priority: P1)

A user runs page cleanup on a dialogue balloon whose detector box is larger than the curved balloon. After cleanup, artwork in the four corners of that box (outside the balloon outline) is unchanged. No rectangular corner smear or fill appears outside the bubble.

**Why this priority**: Exterior corners are the most visible “square” defect and damage art.

**Independent Test**: Synthetic white oval with black outline inside a loose axis-aligned box; run bubble retouch mask / segment; assert no mask pixels in the box corners outside the oval.

**Acceptance Scenarios**:

1. **Given** a dialogue region with a bubble box larger than an oval balloon, **When** the retouch mask is built, **Then** pixels in the box corners outside the balloon outline are not marked for cleanup.
2. **Given** the same page after inpaint, **When** the user inspects those corners, **Then** original art remains (no rectangular cleanup blotches).

---

### User Story 2 - No leftover ring inside near the outline (Priority: P1)

A user runs cleanup on a typical white dialogue balloon. The cleaned interior reaches close to the inner side of the black outline. There is no thick leftover band of original fill between the cleaned area and the outline that reads as a second “contour”.

**Why this priority**: The inner ring makes balloons look outlined twice and leaves uncleared text fringe.

**Independent Test**: Synthetic oval balloon with known outline thickness; measure mask coverage in a thin band just inside the outline; coverage must be high (except the stroke itself).

**Acceptance Scenarios**:

1. **Given** a closed dark-outline balloon with light fill, **When** the retouch mask is built, **Then** the mask covers the light interior near the outline within a small inset (on the order of outline thickness), not a large fixed retreat.
2. **Given** that mask, **When** cleanup runs, **Then** the user does not see a thick uncleared halo hugging the inside of the outline.

---

### User Story 3 - SFX and free text unchanged (Priority: P2)

Sound-effect and free (non-balloon) text still use ink-based masks. Balloon silhouette logic does not replace those paths.

**Why this priority**: Regression guard for existing behavior.

**Independent Test**: Segment an SFX region and a free region; masks remain ink-dilated style, not full balloon fills.

**Acceptance Scenarios**:

1. **Given** an SFX or free region without a usable balloon, **When** segment runs, **Then** the mask follows ink (plus existing pad), not a balloon silhouette fill.

---

### Edge Cases

- Thin or anti-aliased outlines (JPEG): flood must still stop at the stroke; prefer missing a fringe over leaking into AABB corners.
- Balloon with a tail: interior may include the tail cavity if connected and light; must not flood into adjacent panel white through gaps.
- Failed silhouette: fall back to ink dilated inside the search ROI — never an ellipse inscribed in the detector AABB.
- Light-colored outlines: may fail classical barrier; acceptable to fall back to ink path for that region.
- Empty or tiny bubble box: no crash; empty or ink fallback mask.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For dialogue regions with a bubble box, the product MUST build a retouch mask from the **balloon interior silhouette**, not from filling the detector rectangle.
- **FR-002**: The retouch mask MUST NOT mark pixels in the detector box that lie outside the recovered balloon interior (no exterior AABB corner cleanup).
- **FR-003**: The retouch mask MUST reach near the **inner** side of a dark outline (small inset), so a thick uncleared inner ring is not left by a large fixed inset.
- **FR-004**: When silhouette recovery fails, the product MUST fall back to an ink-based mask (within the search ROI), NOT an ellipse inscribed in the bubble AABB.
- **FR-005**: SFX and regions without a bubble box MUST keep the existing ink-mask behavior.
- **FR-006**: Tunable inset / barrier defaults MUST live in Config with safe defaults (constitution).
- **FR-007**: Existing flat-fill behavior for uniform white balloons MUST remain available (LaMa path not required to change unless needed to meet FR-002/003).

### Key Entities

- **Bubble interior silhouette**: binary mask of light interior connected to text seeds, stopped by outline barrier.
- **Retouch mask**: mask passed to cleanup for dialogue (silhouette after small inset, covering letter ink).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the synthetic oval-in-AABB fixture, retouch mask ∩ (AABB corners ∖ oval interior) is empty.
- **SC-002**: On the same fixture, coverage of light pixels in a 1–3 px band just inside the outline (excluding the stroke) is high enough that no thick uncleared ring remains (unit threshold documented in tests).
- **SC-003**: Unit tests for bubble contour and existing segment/lama suites pass.
- **SC-004**: Manual spot-check on a real dialogue page shows no rectangular exterior corners and no thick inner contour ring after cleanup.

## Assumptions

- Detector still provides AABB only; no new balloon segmentation model in this feature.
- Typical dialogue balloons have a darker outline than the interior fill.
- Specs 010/011 (LaMa ring / soft edges) remain; this feature owns silhouette geometry upstream of inpaint.

## Out of Scope

- Learned balloon instance segmentation (YOLO/U-Net).
- Active-contour snakes.
- Replacing the bubble detector model.
- Flutter / LAN contract changes.
