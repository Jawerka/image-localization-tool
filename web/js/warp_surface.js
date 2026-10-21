/** Геометрия локального warp: те же формулы, что в Dart-превью. */

export const BEND_WARPS = ["arc", "wave", "flag", "ring"];

export function buildWarpPositions(kind, width, height, bend, columns, rows) {
  const maxX = Math.max(0, width - 1);
  const maxY = Math.max(0, height - 1);
  if (width < 2 || height < 2) return [];
  const centerX = maxX / 2;
  const centerY = maxY / 2;
  const radiusMax = Math.max(centerX, centerY, 1);
  const ampX = bend * width * 0.08;
  const ampY = bend * height * 0.08;
  const points = [];
  for (let iy = 0; iy <= rows; iy += 1) {
    const sy = (iy / rows) * maxY;
    for (let ix = 0; ix <= columns; ix += 1) {
      const sx = (ix / columns) * maxX;
      let x = sx;
      let y = sy;
      if (kind === "wave") {
        for (let step = 0; step < 4; step += 1) {
          const nextX = sx + ampX * Math.sin((2 * Math.PI * y) / Math.max(1, maxY));
          const nextY = sy + ampY * Math.sin((2 * Math.PI * x) / Math.max(1, maxX));
          x = nextX;
          y = nextY;
        }
      } else if (kind === "flag") {
        y = sy + ampY * Math.sin((2 * Math.PI * sx) / Math.max(1, maxX));
      } else if (kind === "arc") {
        const normX = (sx - centerX) / Math.max(1, centerX);
        y = sy - bend * height * (1 - normX * normX) + bend * width;
        x = sx;
      } else if (kind === "ring") {
        const sourceX = sx - centerX;
        const sourceY = sy - centerY;
        const sourceRadius = Math.sqrt(sourceX * sourceX + sourceY * sourceY);
        const sourceAngle = Math.atan2(sourceY, sourceX);
        let radius = sourceRadius;
        for (let step = 0; step < 6; step += 1) {
          const norm = radius / Math.max(1, radiusMax);
          radius = sourceRadius * Math.max(1 + bend * 0.2 * norm, 0.05);
        }
        const norm = radius / Math.max(1, radiusMax);
        const angle = sourceAngle - bend * norm;
        x = centerX + radius * Math.cos(angle);
        y = centerY + radius * Math.sin(angle);
      }
      points.push([x, y]);
    }
  }
  return points;
}
