/** Цветной композит маски: чёрный негатив и ручные назначения. */

export const MASK_ADD_COLOR = "#90EE90";
export const MASK_REMOVE_COLOR = "#FF9999";

/** Цвет последнего ручного действия в пикселе. */
export function modeColor(mode) {
  return mode === "erase" || mode === "erase_fill"
    ? MASK_REMOVE_COLOR
    : MASK_ADD_COLOR;
}

/**
 * Grayscale → чёрный с alpha = 255 − M.
 * Меняет RGBA-буфер на месте (ImageData.data).
 */
export function grayToBlackOverlay(pixels) {
  for (let index = 0; index < pixels.length; index += 4) {
    const gray = pixels[index];
    pixels[index] = 0;
    pixels[index + 1] = 0;
    pixels[index + 2] = 0;
    pixels[index + 3] = 255 - gray;
  }
  return pixels;
}

/** Штрихи, которых ещё нет в маске: только их рисуем цветом. */
export function unbakedStrokes(strokes, bakedCount) {
  if (!Array.isArray(strokes) || !strokes.length) return [];
  const baked = Math.max(0, Math.min(Number(bakedCount) || 0, strokes.length));
  return strokes.slice(baked);
}

/** Ключ кэша: маска принадлежит конкретной странице, версии и размеру. */
export function maskBaseKey(src, width, height) {
  return `${src || ""}|${width || 0}x${height || 0}`;
}
