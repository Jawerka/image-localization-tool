/* Геометрия warp-сетки 4×4. Узлы назначения задаются row-major. */

function normalizeMesh(mesh) {
  if (!Array.isArray(mesh)) return null;
  let points = mesh;
  if (mesh.length === 4 && mesh.every((row) => Array.isArray(row) && row.length === 4 && Array.isArray(row[0]))) {
    points = mesh.flat();
  }
  if (points.length !== 16) return null;
  const normalized = points.map((point) => [Number(point?.[0]), Number(point?.[1])]);
  if (normalized.some((point) => !point.every(Number.isFinite))) return null;
  return Array.from({ length: 4 }, (_, row) => normalized.slice(row * 4, row * 4 + 4));
}

function cellVectors(points, row, col) {
  const p00 = points[row][col];
  const p10 = points[row][col + 1];
  const p01 = points[row + 1][col];
  const p11 = points[row + 1][col + 1];
  const a = [p10[0] - p00[0], p10[1] - p00[1]];
  const b = [p01[0] - p00[0], p01[1] - p00[1]];
  const c = [p11[0] - p10[0] - p01[0] + p00[0], p11[1] - p10[1] - p01[1] + p00[1]];
  return { p00, a, b, c };
}

function validCell({ a, b, c }) {
  const determinants = [
    a[0] * b[1] - a[1] * b[0],
    a[0] * (b[1] + c[1]) - a[1] * (b[0] + c[0]),
    (a[0] + c[0]) * b[1] - (a[1] + c[1]) * b[0],
    (a[0] + c[0]) * (b[1] + c[1]) - (a[1] + c[1]) * (b[0] + c[0]),
  ];
  return determinants.every((value) => Number.isFinite(value) && value > 1e-6);
}

function solveCell(target, cell) {
  const { p00, a, b, c } = cell;
  let u = 0.5;
  let v = 0.5;
  for (let index = 0; index < 10; index += 1) {
    const fx = p00[0] + u * a[0] + v * b[0] + u * v * c[0] - target[0];
    const fy = p00[1] + u * a[1] + v * b[1] + u * v * c[1] - target[1];
    const j00 = a[0] + v * c[0];
    const j01 = b[0] + u * c[0];
    const j10 = a[1] + v * c[1];
    const j11 = b[1] + u * c[1];
    const determinant = j00 * j11 - j01 * j10;
    if (!Number.isFinite(determinant) || Math.abs(determinant) <= 1e-9) return null;
    u -= (fx * j11 - fy * j01) / determinant;
    v -= (j00 * fy - j10 * fx) / determinant;
  }
  const residualX = p00[0] + u * a[0] + v * b[0] + u * v * c[0] - target[0];
  const residualY = p00[1] + u * a[1] + v * b[1] + u * v * c[1] - target[1];
  if (Math.abs(residualX) > 1e-3 || Math.abs(residualY) > 1e-3 || u < -1e-5 || u > 1.00001 || v < -1e-5 || v > 1.00001) return null;
  return [u, v];
}

/** Назначение → источник для общего контракта Python/JS. */
export function invertMeshPoint(point, mesh, width, height) {
  const points = normalizeMesh(mesh);
  const x = Number(point?.[0]);
  const y = Number(point?.[1]);
  if (!points || !Number.isFinite(x) || !Number.isFinite(y) || width < 2 || height < 2) return null;
  if (!isValidMesh(points)) return null;
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      const cell = cellVectors(points, row, col);
      const corners = [points[row][col], points[row][col + 1], points[row + 1][col], points[row + 1][col + 1]];
      if (x < Math.min(...corners.map((item) => item[0])) - 1e-5 || x > Math.max(...corners.map((item) => item[0])) + 1e-5
        || y < Math.min(...corners.map((item) => item[1])) - 1e-5 || y > Math.max(...corners.map((item) => item[1])) + 1e-5) continue;
      const uv = solveCell([x, y], cell);
      if (!uv) continue;
      return [((col + uv[0]) / 3) * (width - 1), ((row + uv[1]) / 3) * (height - 1)];
    }
  }
  return null;
}

export function isValidMesh(mesh) {
  const points = normalizeMesh(mesh);
  if (!points) return false;
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      if (!validCell(cellVectors(points, row, col))) return false;
    }
  }
  return true;
}

/** Прямое отображение исходной точки по билинейной поверхности mesh v2. */
export function mapMeshForward(point, mesh, width, height) {
  const points = normalizeMesh(mesh);
  const x = Number(point?.[0]);
  const y = Number(point?.[1]);
  if (!points || !isValidMesh(points) || !Number.isFinite(x) || !Number.isFinite(y)
    || width < 2 || height < 2 || x < 0 || y < 0 || x > width || y > height) return null;
  const gx = (x / width) * 3;
  const gy = (y / height) * 3;
  const col = Math.min(2, Math.floor(gx));
  const row = Math.min(2, Math.floor(gy));
  const u = Math.min(1, gx - col);
  const v = Math.min(1, gy - row);
  const { p00, a, b, c } = cellVectors(points, row, col);
  return [
    p00[0] + u * a[0] + v * b[0] + u * v * c[0],
    p00[1] + u * a[1] + v * b[1] + u * v * c[1],
  ];
}
