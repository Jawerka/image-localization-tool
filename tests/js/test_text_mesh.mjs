import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { invertMeshPoint, isValidMesh, mapMeshForward } from "../../web/js/text_mesh.js";

const vectors = JSON.parse(readFileSync(new URL("../fixtures/text_mesh_vectors.json", import.meta.url), "utf8"));

function destination(mesh, source, width, height) {
  const gx = source[0] / (width - 1) * 3;
  const gy = source[1] / (height - 1) * 3;
  const col = Math.min(2, Math.floor(gx));
  const row = Math.min(2, Math.floor(gy));
  const u = gx - col;
  const v = gy - row;
  const points = Array.from({ length: 4 }, (_, r) => mesh.slice(r * 4, r * 4 + 4));
  const p00 = points[row][col];
  const p10 = points[row][col + 1];
  const p01 = points[row + 1][col];
  const p11 = points[row + 1][col + 1];
  return [0, 1].map((axis) => p00[axis]
    + u * (p10[axis] - p00[axis])
    + v * (p01[axis] - p00[axis])
    + u * v * (p11[axis] - p10[axis] - p01[axis] + p00[axis]));
}

describe("text mesh shared geometry", () => {
  for (const item of vectors.cases) {
    it(`inverts ${item.name} destination nodes`, () => {
      const target = destination(item.mesh, item.source, vectors.width, vectors.height);
      const source = invertMeshPoint(target, item.mesh, vectors.width, vectors.height);
      assert.ok(source, "point must be inside a valid cell");
      assert.ok(Math.abs(source[0] - item.source[0]) <= 1e-3);
      assert.ok(Math.abs(source[1] - item.source[1]) <= 1e-3);
    });
  }

  it("rejects a folded cell", () => {
    const mesh = vectors.cases[0].mesh.map((point) => point.slice());
    [mesh[5], mesh[6]] = [mesh[6], mesh[5]];
    assert.equal(isValidMesh(mesh), false);
    assert.equal(invertMeshPoint([40, 30], mesh, vectors.width, vectors.height), null);
  });

  it("maps identity and affine source points forward", () => {
    const width = 96;
    const height = 64;
    const identity = Array.from({ length: 16 }, (_, index) => [
      (index % 4) * width / 3,
      Math.floor(index / 4) * height / 3,
    ]);
    const source = [43.5, 22.25];
    const same = mapMeshForward(source, identity, width, height);
    assert.ok(same);
    assert.ok(Math.abs(same[0] - source[0]) < 1e-6);
    assert.ok(Math.abs(same[1] - source[1]) < 1e-6);

    const affine = identity.map(([x, y]) => [x * 1.25 + 7, y * 0.75 - 3]);
    const mapped = mapMeshForward(source, affine, width, height);
    assert.ok(mapped);
    assert.ok(Math.abs(mapped[0] - (source[0] * 1.25 + 7)) < 1e-6);
    assert.ok(Math.abs(mapped[1] - (source[1] * 0.75 - 3)) < 1e-6);
  });
});
