/** Локальная маска при deferApply: чистая логика без DOM-обвязки viewer. */

/**
 * Что делать с локальным оверлеем маски.
 * @returns {"paint"|"wait"|"clear"}
 */
export function maskDraftAction({
  deferredApply = false,
  pageId = "",
  draftPageId = "",
  pageBusy = false,
} = {}) {
  const active = String(pageId || "");
  if (!active) return "clear";
  if (deferredApply) return "paint";
  if (draftPageId && String(draftPageId) === active && pageBusy) return "wait";
  return "clear";
}

/** Нормализовать штрих для отрисовки маски. */
export function normalizeMaskStroke(stroke) {
  const item = stroke && typeof stroke === "object" ? stroke : {};
  const radius = Math.max(1, Math.round(Number(item.radius) || 1));
  const points = Array.isArray(item.points)
    ? item.points.map((point) => [Number(point?.[0]) || 0, Number(point?.[1]) || 0])
    : [];
  let mode = "paint";
  if (item.mode === "erase") mode = "erase";
  else if (item.mode === "fill") mode = "fill";
  else if (item.mode === "erase_fill") mode = "erase_fill";
  else if (item.mode === "flood") mode = "flood";
  else if (item.mode === "erase_flood") mode = "erase_flood";
  const color = mode === "erase" || mode === "erase_fill" || mode === "erase_flood" ? "#000000" : "#ffffff";
  const tolerance = Math.max(0, Math.min(100, Number(item.tolerance) || 0));
  return { mode, radius, points, color, tolerance };
}

/**
 * Как ``apply_strokes`` в text_segmenter: линия thickness=2r, круги радиуса r,
 * либо заливка полигона для mode=fill.
 * ``ctx`` — CanvasRenderingContext2D или совместимый мок.
 */
export function paintStrokeOnMask(ctx, stroke, color) {
  if (!ctx) return;
  const normalized = normalizeMaskStroke(stroke);
  const { mode, radius, points } = normalized;
  const ink = color || normalized.color;
  if (!points.length) return;
  ctx.fillStyle = ink;
  ctx.strokeStyle = ink;
  ctx.lineWidth = Math.max(1, radius * 2);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (mode === "fill" || mode === "erase_fill") {
    if (points.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let index = 1; index < points.length; index += 1) {
      ctx.lineTo(points[index][0], points[index][1]);
    }
    ctx.closePath();
    ctx.fill();
    return;
  }
  if (points.length === 1) {
    ctx.beginPath();
    ctx.arc(points[0][0], points[0][1], radius, 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let index = 1; index < points.length; index += 1) {
    ctx.lineTo(points[index][0], points[index][1]);
  }
  ctx.stroke();
  for (const point of points) {
    ctx.beginPath();
    ctx.arc(point[0], point[1], radius, 0, Math.PI * 2);
    ctx.fill();
  }
}
