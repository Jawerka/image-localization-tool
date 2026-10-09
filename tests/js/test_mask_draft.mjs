import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  maskDraftAction,
  normalizeMaskStroke,
  paintStrokeOnMask,
} from "../../web/js/mask_draft.js";

describe("maskDraftAction", () => {
  it("clears without page", () => {
    assert.equal(maskDraftAction({ deferredApply: true }), "clear");
  });

  it("paints while deferred", () => {
    assert.equal(
      maskDraftAction({ deferredApply: true, pageId: "p1", draftPageId: "p1" }),
      "paint",
    );
  });

  it("waits after Done while page busy", () => {
    assert.equal(
      maskDraftAction({
        deferredApply: false,
        pageId: "p1",
        draftPageId: "p1",
        pageBusy: true,
      }),
      "wait",
    );
  });

  it("clears when idle and not deferred", () => {
    assert.equal(
      maskDraftAction({
        deferredApply: false,
        pageId: "p1",
        draftPageId: "p1",
        pageBusy: false,
      }),
      "clear",
    );
  });

  it("clears when draft belongs to another page", () => {
    assert.equal(
      maskDraftAction({
        deferredApply: false,
        pageId: "p2",
        draftPageId: "p1",
        pageBusy: true,
      }),
      "clear",
    );
  });
});

describe("normalizeMaskStroke / paintStrokeOnMask", () => {
  it("normalizes erase color and radius", () => {
    const stroke = normalizeMaskStroke({ mode: "erase", radius: 3.2, points: [[1, 2]] });
    assert.equal(stroke.mode, "erase");
    assert.equal(stroke.radius, 3);
    assert.equal(stroke.color, "#000000");
    assert.deepEqual(stroke.points, [[1, 2]]);
  });

  it("paints a single point as a filled arc", () => {
    const calls = [];
    const ctx = {
      beginPath() { calls.push("begin"); },
      arc(x, y, r) { calls.push(["arc", x, y, r]); },
      fill() { calls.push("fill"); },
      stroke() { calls.push("stroke"); },
      moveTo() { calls.push("move"); },
      lineTo() { calls.push("line"); },
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 0,
      lineCap: "",
      lineJoin: "",
    };
    paintStrokeOnMask(ctx, { mode: "paint", radius: 4, points: [[10, 20]] });
    assert.equal(ctx.fillStyle, "#ffffff");
    assert.equal(ctx.lineWidth, 8);
    assert.deepEqual(calls, ["begin", ["arc", 10, 20, 4], "fill"]);
  });

  it("strokes a polyline then fills endpoint caps", () => {
    const calls = [];
    const ctx = {
      beginPath() { calls.push("begin"); },
      arc(x, y, r) { calls.push(["arc", x, y, r]); },
      fill() { calls.push("fill"); },
      stroke() { calls.push("stroke"); },
      moveTo(x, y) { calls.push(["move", x, y]); },
      lineTo(x, y) { calls.push(["line", x, y]); },
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 0,
      lineCap: "",
      lineJoin: "",
    };
    paintStrokeOnMask(ctx, { mode: "erase", radius: 2, points: [[0, 0], [5, 5]] });
    assert.equal(ctx.fillStyle, "#000000");
    assert.ok(calls.includes("stroke"));
    assert.ok(calls.some((item) => Array.isArray(item) && item[0] === "arc"));
  });
});
