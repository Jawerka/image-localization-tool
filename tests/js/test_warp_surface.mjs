import test from "node:test";
import assert from "node:assert/strict";

import { BEND_WARPS, buildWarpPositions } from "../../web/js/warp_surface.js";

const COLUMNS = 8;
const ROWS = 6;

test("bend warps are identity at zero bend", () => {
  for (const kind of BEND_WARPS) {
    const points = buildWarpPositions(kind, 120, 60, 0, COLUMNS, ROWS);
    assert.equal(points.length, (COLUMNS + 1) * (ROWS + 1));
    for (let row = 0; row <= ROWS; row += 1) {
      for (let col = 0; col <= COLUMNS; col += 1) {
        const point = points[row * (COLUMNS + 1) + col];
        assert.ok(Math.abs(point[0] - (col / COLUMNS) * 119) < 1e-6);
        assert.ok(Math.abs(point[1] - (row / ROWS) * 59) < 1e-6);
      }
    }
  }
});

test("bend warps stay finite and change geometry", () => {
  for (const kind of BEND_WARPS) {
    const points = buildWarpPositions(kind, 120, 60, 0.4, COLUMNS, ROWS);
    assert.ok(points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y)));
    const moved = points.some(([x, y], index) => {
      const baseX = ((index % (COLUMNS + 1)) / COLUMNS) * 119;
      const row = Math.floor(index / (COLUMNS + 1));
      const baseY = (row / ROWS) * 59;
      return Math.abs(x - baseX) > 0.5 || Math.abs(y - baseY) > 0.5;
    });
    assert.ok(moved, `${kind} should move points`);
  }
});

test("shared warp fixture matches Dart/JS samples", async () => {
  const { readFile } = await import("node:fs/promises");
  const path = new URL("../fixtures/local_warp_samples.json", import.meta.url);
  const fixture = JSON.parse(await readFile(path, "utf8"));
  for (const [kind, expected] of Object.entries(fixture.kinds)) {
    const points = buildWarpPositions(
      kind,
      fixture.width,
      fixture.height,
      fixture.bend,
      fixture.columns,
      fixture.rows,
    );
    fixture.indices.forEach((index, position) => {
      assert.ok(Math.abs(points[index][0] - expected[position][0]) < 1e-3);
      assert.ok(Math.abs(points[index][1] - expected[position][1]) < 1e-3);
    });
  }
});
