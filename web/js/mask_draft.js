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
  const mode = item.mode === "erase" ? "erase" : "paint";
  return { mode, radius, points, color: mode === "erase" ? "#000000" : "#ffffff" };
}

/**
 * Как ``apply_strokes`` в text_segmenter: линия thickness=2r, круги радиуса r.
 * ``ctx`` — CanvasRenderingContext2D или совместимый мок.
 */
export function paintStrokeOnMask(ctx, stroke) {
  if (!ctx) return;
  const { radius, points, color } = normalizeMaskStroke(stroke);
  if (!points.length) return;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, radius * 2);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
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
