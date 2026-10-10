import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  brushModeFromButton,
  editorSessionToWire,
  fitWidthScale,
  normalizeEditorSession,
  polylineModeFromButton,
  resolveActivePageId,
} from "../../web/js/editor_session.js";

describe("resolveActivePageId", () => {
  const pages = [{ id: "a" }, { id: "b" }, { id: "c" }];

  it("keeps preferred page when present", () => {
    assert.equal(resolveActivePageId(pages, "b"), "b");
  });

  it("falls back to first when missing", () => {
    assert.equal(resolveActivePageId(pages, "missing"), "a");
  });
});

describe("normalizeEditorSession / wire", () => {
  it("round-trips snake_case fields", () => {
    const normalized = normalizeEditorSession({
      active_page_id: "p2",
      zoom: "fit-width",
      scroll_left: 12,
      scroll_top: 34,
    });
    assert.deepEqual(normalized, {
      activePageId: "p2",
      zoom: "fit-width",
      scrollLeft: 12,
      scrollTop: 34,
    });
    assert.deepEqual(editorSessionToWire(normalized), {
      active_page_id: "p2",
      zoom: "fit-width",
      scroll_left: 12,
      scroll_top: 34,
    });
  });

  it("accepts numeric zoom", () => {
    assert.equal(normalizeEditorSession({ zoom: 1.25 }).zoom, 1.25);
  });
});

describe("fitWidthScale", () => {
  it("matches stage width minus padding over image width", () => {
    assert.equal(fitWidthScale(816, 800, 16), 1);
    assert.equal(fitWidthScale(416, 800, 16), 0.5);
  });
});

describe("dual button modes", () => {
  it("brush LMB paint RMB erase", () => {
    assert.equal(brushModeFromButton(0), "paint");
    assert.equal(brushModeFromButton(2), "erase");
  });

  it("lasso LMB fill RMB erase_fill", () => {
    assert.equal(polylineModeFromButton(0), "fill");
    assert.equal(polylineModeFromButton(2), "erase_fill");
  });
});
