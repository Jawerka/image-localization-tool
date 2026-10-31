import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  detailsOpenFromMap,
  inspectorContentKey,
  inspectorInteractionActive,
  shouldSkipInspectorRebuild,
} from "../../web/js/inspector_render.js";

describe("inspectorContentKey", () => {
  it("ignores job noise and changes with translation", () => {
    const base = {
      activePageId: "p1",
      selectedRegionId: "1",
      document: { regions: [{ id: 1, text: "Hi", translation: "Привет", style: {} }] },
      fonts: [],
      styleLibrary: [],
      job: { progress: 10 },
    };
    const a = inspectorContentKey(base);
    const b = inspectorContentKey({ ...base, job: { progress: 90 } });
    assert.equal(a, b);
    const c = inspectorContentKey({
      ...base,
      document: { regions: [{ id: 1, text: "Hi", translation: "Здравствуй", style: {} }] },
    });
    assert.notEqual(a, c);
  });

  it("changes when original text changes", () => {
    const base = {
      activePageId: "p1",
      selectedRegionId: "1",
      document: { regions: [{ id: 1, text: "Hi", translation: "", style: {} }] },
      fonts: [],
      styleLibrary: [],
    };
    const a = inspectorContentKey(base);
    const b = inspectorContentKey({
      ...base,
      document: { regions: [{ id: 1, text: "Hello", translation: "", style: {} }] },
    });
    assert.notEqual(a, b);
  });
});

describe("shouldSkipInspectorRebuild", () => {
  it("skips when key unchanged", () => {
    assert.equal(shouldSkipInspectorRebuild("k", "k"), true);
  });

  it("rebuilds when key changed", () => {
    assert.equal(shouldSkipInspectorRebuild("a", "b"), false);
  });

  it("rebuilds when only selectedRegionId changes", () => {
    const doc = { regions: [{ id: 1, text: "Hi", translation: "", style: {} }] };
    const a = inspectorContentKey({
      activePageId: "p1",
      selectedRegionId: "1",
      document: doc,
      fonts: [],
      styleLibrary: [],
    });
    const b = inspectorContentKey({
      activePageId: "p1",
      selectedRegionId: "2",
      document: doc,
      fonts: [],
      styleLibrary: [],
    });
    assert.notEqual(a, b);
    assert.equal(shouldSkipInspectorRebuild(a, b), false);
  });
});

describe("inspectorInteractionActive", () => {
  it("ignores region head button focus", () => {
    const head = { closest: (sel) => (sel === ".region-card__head" ? {} : null) };
    const root = { contains: () => true };
    const focus = { tagName: "BUTTON", closest: head.closest, isContentEditable: false };
    assert.equal(inspectorInteractionActive(root, focus), false);
  });

  it("detects select focus", () => {
    const root = { contains: () => true };
    const focus = {
      tagName: "SELECT",
      closest: () => null,
      isContentEditable: false,
    };
    assert.equal(inspectorInteractionActive(root, focus), true);
  });
});

describe("detailsOpenFromMap", () => {
  it("restores per-region open flags", () => {
    const map = { "7": { warp: false, styles: true } };
    assert.equal(detailsOpenFromMap(map, 7, "warp", true), "");
    assert.equal(detailsOpenFromMap(map, 7, "styles", false), " open");
    assert.equal(detailsOpenFromMap(map, 9, "warp", true), " open");
  });
});
