import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  clampApplyChipOffset,
  isApplyChipDrag,
  snapApplyChipOffset,
} from "../../web/js/apply_chip.js";

describe("clampApplyChipOffset", () => {
  it("keeps offset inside host minus chip and padding", () => {
    assert.equal(clampApplyChipOffset(0, 400, 80, 8), 0);
    assert.equal(clampApplyChipOffset(500, 400, 80, 8), 152);
    assert.equal(clampApplyChipOffset(-500, 400, 80, 8), -152);
  });

  it("returns 0 when chip fills the host", () => {
    assert.equal(clampApplyChipOffset(20, 100, 100, 0), 0);
  });
});

describe("snapApplyChipOffset", () => {
  it("snaps to center within threshold", () => {
    assert.equal(snapApplyChipOffset(20, 32), 0);
    assert.equal(snapApplyChipOffset(-31, 32), 0);
  });

  it("keeps offset outside threshold", () => {
    assert.equal(snapApplyChipOffset(40, 32), 40);
    assert.equal(snapApplyChipOffset(-50, 32), -50);
  });
});

describe("isApplyChipDrag", () => {
  it("ignores small movement as click", () => {
    assert.equal(isApplyChipDrag(0), false);
    assert.equal(isApplyChipDrag(6), false);
  });

  it("treats larger movement as drag", () => {
    assert.equal(isApplyChipDrag(7), true);
    assert.equal(isApplyChipDrag(-10), true);
  });
});
