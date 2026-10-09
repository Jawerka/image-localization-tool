# Feature Specification: Soft LaMa Mask Edges

**Feature Branch**: `011-soft-mask-edges`

**Created**: 2026-10-09

**Status**: Draft

**Input**: Soft paste feather for LaMa/OpenCV inpaint so hole edges blend into the original and do not hard-cut or stretch the background. Binary hole mask into the model unchanged. Flat-fill path unchanged. Flutter out of scope.

## User Scenarios & Testing

### User Story 1 - Soft edge on neural/OpenCV cleanup (Priority: P1)

When cleanup fills a non-flat hole, the boundary between predicted fill and original art fades over a few pixels instead of a hard seam.

**Acceptance**: Unit test shows a border pixel is a blend; a deep interior pixel matches predicted.

### User Story 2 - Hard paste when feather is zero (Priority: P2)

With feather width 0, paste behavior matches the previous hard replacement (regression).

## Requirements

- **FR-001**: Paste of LaMa/OpenCV prediction MUST blend with original using distance-to-edge alpha inside the component.
- **FR-002**: Model/OpenCV input mask MUST remain binary.
- **FR-003**: Flat-fill / halo path MUST not use this feather.
- **FR-004**: Feather width 0 MUST equal hard paste.
- **FR-005**: Flutter out of scope.

## Success Criteria

- **SC-001**: `test_lama_inpainter` passes including new soft-paste cases.
- **SC-002**: Visible seam at balloon edges is softer on dense pages (manual).
