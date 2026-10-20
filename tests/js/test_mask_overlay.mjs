import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { paintStrokeOnMask } from "../../web/js/mask_draft.js";
import {
  MASK_ADD_COLOR,
  MASK_REMOVE_COLOR,
  grayToBlackOverlay,
  maskBaseKey,
  modeColor,
  unbakedStrokes,
} from "../../web/js/mask_overlay.js";

function mockContext() {
  return {
    beginPath() {},
    closePath() {},
    arc() {},
    fill() {},
    stroke() {},
    moveTo() {},
    lineTo() {},
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
    lineCap: "",
    lineJoin: "",
  };
}

describe("modeColor", () => {
  it("uses green for paint and fill", () => {
    assert.equal(modeColor("paint"), MASK_ADD_COLOR);
    assert.equal(modeColor("fill"), MASK_ADD_COLOR);
    assert.equal(MASK_ADD_COLOR, "#90EE90");
  });

  it("uses red for erase and erase_fill", () => {
    assert.equal(modeColor("erase"), MASK_REMOVE_COLOR);
    assert.equal(modeColor("erase_fill"), MASK_REMOVE_COLOR);
    assert.equal(MASK_REMOVE_COLOR, "#FF9999");
  });
});

describe("grayToBlackOverlay", () => {
  it("maps black to opaque black", () => {
    const pixels = new Uint8ClampedArray([0, 0, 0, 255]);
    grayToBlackOverlay(pixels);
    assert.deepEqual([...pixels], [0, 0, 0, 255]);
  });

  it("maps white to transparent", () => {
    const pixels = new Uint8ClampedArray([255, 255, 255, 255]);
    grayToBlackOverlay(pixels);
    assert.deepEqual([...pixels], [0, 0, 0, 0]);
  });

  it("keeps gray gradation in alpha", () => {
    const pixels = new Uint8ClampedArray([
      128, 128, 128, 255,
      200, 200, 200, 255,
    ]);
    grayToBlackOverlay(pixels);
    assert.deepEqual([...pixels], [0, 0, 0, 127, 0, 0, 0, 55]);
  });
});

describe("unbakedStrokes", () => {
  it("returns only strokes added after the baked count", () => {
    const strokes = [{ mode: "paint" }, { mode: "erase" }, { mode: "fill" }];
    assert.deepEqual(unbakedStrokes(strokes, 2), [{ mode: "fill" }]);
    assert.deepEqual(unbakedStrokes(strokes, 0), strokes);
    assert.deepEqual(unbakedStrokes(strokes, 3), []);
    assert.deepEqual(unbakedStrokes(strokes, 99), []);
  });

  it("handles empty and missing lists", () => {
    assert.deepEqual(unbakedStrokes([], 5), []);
    assert.deepEqual(unbakedStrokes(null, 5), []);
  });
});

describe("maskBaseKey", () => {
  it("separates pages and sizes", () => {
    assert.notEqual(maskBaseKey("/p1/mask", 10, 20), maskBaseKey("/p2/mask", 10, 20));
    assert.notEqual(maskBaseKey("/p1/mask", 10, 20), maskBaseKey("/p1/mask", 20, 10));
  });
});

describe("paintStrokeOnMask color override", () => {
  it("paints with the requested color instead of binary white/black", () => {
    const ctx = mockContext();
    paintStrokeOnMask(ctx, { mode: "paint", radius: 2, points: [[1, 1], [4, 4]] }, MASK_ADD_COLOR);
    assert.equal(ctx.fillStyle, MASK_ADD_COLOR);
    assert.equal(ctx.strokeStyle, MASK_ADD_COLOR);
  });

  it("keeps the binary wrapper for callers without a color", () => {
    const ctx = mockContext();
    paintStrokeOnMask(ctx, { mode: "erase", radius: 2, points: [[1, 1]] });
    assert.equal(ctx.fillStyle, "#000000");
  });
});
