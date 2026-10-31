import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { REGION_TABS, regionTabFor, regionTabKey, setRegionTab } from "../../web/js/region_tabs.js";

describe("region tabs", () => {
  it("defaults to text and remembers the chosen tab", () => {
    const map = new Map();
    const state = { project: { id: "pr" }, activePageId: "p1" };
    assert.equal(regionTabFor(map, state, "1"), "text");
    setRegionTab(map, state, "1", "transform");
    assert.equal(regionTabFor(map, state, "1"), "transform");
    assert.equal(regionTabFor(map, state, "2"), "text");
  });

  it("separates pages and projects", () => {
    const map = new Map();
    const state = { project: { id: "pr" }, activePageId: "p1" };
    setRegionTab(map, state, "1", "font");
    assert.equal(regionTabFor(map, { ...state, activePageId: "p2" }, "1"), "text");
    assert.equal(regionTabFor(map, { ...state, project: { id: "pr2" } }, "1"), "text");
    assert.notEqual(regionTabKey(state, "1"), regionTabKey({ ...state, activePageId: "p2" }, "1"));
  });

  it("ignores unknown tabs and exposes three panels", () => {
    const map = new Map();
    const state = { project: null, activePageId: "" };
    setRegionTab(map, state, "1", "nope");
    assert.equal(regionTabFor(map, state, "1"), "text");
    assert.deepEqual(REGION_TABS.map(([id]) => id), ["text", "font", "transform"]);
  });
});
