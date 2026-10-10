import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  isDeferredPending,
  nextDeferredBaseline,
  shouldDeferEdit,
  shouldPushHistory,
} from "../../web/js/deferred_edits.js";

describe("shouldDeferEdit", () => {
  it("defers when option set", () => {
    assert.equal(shouldDeferEdit(true, false), true);
  });

  it("stays deferred when session already open", () => {
    assert.equal(shouldDeferEdit(false, true), true);
  });

  it("does not defer when neither", () => {
    assert.equal(shouldDeferEdit(false, false), false);
  });
});

describe("nextDeferredBaseline", () => {
  it("keeps existing baseline", () => {
    assert.equal(nextDeferredBaseline("base-a", "doc-b"), "base-a");
  });

  it("records key before first deferred edit", () => {
    assert.equal(nextDeferredBaseline("", "doc-before"), "doc-before");
  });
});

describe("isDeferredPending", () => {
  it("pending while document differs from baseline", () => {
    assert.equal(isDeferredPending("after", "before"), true);
  });

  it("clears when back to baseline", () => {
    assert.equal(isDeferredPending("before", "before"), false);
  });

  it("not pending without baseline", () => {
    assert.equal(isDeferredPending("anything", ""), false);
  });
});

describe("shouldPushHistory (stroke coalesce)", () => {
  it("pushes a new step when coalesce key is empty", () => {
    assert.equal(shouldPushHistory("", "stroke"), true);
  });

  it("does not merge distinct empty-key strokes into one step", () => {
    // Каждый pointerup без coalesce → отдельный undo (SC-001).
    let prev = "";
    let steps = 0;
    for (let i = 0; i < 3; i += 1) {
      const key = "";
      if (shouldPushHistory(key, prev)) {
        steps += 1;
        prev = key;
      }
      if (!key) prev = "";
    }
    assert.equal(steps, 3);
  });

  it("shared stroke coalesce would wrongly collapse steps", () => {
    let prev = "";
    let steps = 0;
    for (let i = 0; i < 3; i += 1) {
      const key = "stroke";
      if (shouldPushHistory(key, prev)) {
        steps += 1;
        prev = key;
      }
    }
    assert.equal(steps, 1);
  });

  it("coalesces continuous font slider under one key", () => {
    let prev = "";
    let steps = 0;
    for (let i = 0; i < 5; i += 1) {
      const key = "font:7";
      if (shouldPushHistory(key, prev)) {
        steps += 1;
        prev = key;
      }
    }
    assert.equal(steps, 1);
  });
});
