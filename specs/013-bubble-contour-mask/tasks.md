# Tasks: Bubble Contour Mask

## Phase 1 — Setup

- [x] T001 Create `specs/013-bubble-contour-mask/` artifacts (spec/plan/research/…)
- [x] T002 Branch `013-bubble-contour-mask`

## Phase 2 — Foundational

- [x] T003 Add `Config.bubble_mask_inset_px` default 2
- [x] T004 Implement `src/components/bubble_contour.py` (`bubble_interior_mask`)
- [x] T005 Wire `text_segmenter`: use bubble_contour; remove inscribed-ellipse retouch fallback

## Phase 3 — User stories

- [x] T006 [US1] Unit `test_no_aabb_corner_pixels` (oval in loose AABB)
- [x] T007 [US2] Unit `test_inner_coverage_near_outline`
- [x] T008 [US3] Confirm SFX/free still ink path (existing or small unit)

## Phase 4 — Polish

- [x] T009 Run pytest bubble_contour + page_steps / related
- [x] T010 Mark tasks complete; note manual check in quickstart

## Dependencies

T003 → T004 → T005 → T006/T007 → T009
