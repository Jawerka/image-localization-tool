/** Сессия редактора: активная страница, zoom, scroll (для пакета .ilt.zip). */

/**
 * Нормализовать editor из API / manifest.
 * @returns {{ activePageId: string, zoom: string|number, scrollLeft: number, scrollTop: number }|null}
 */
export function normalizeEditorSession(raw) {
  if (!raw || typeof raw !== "object") return null;
  const activePageId = String(raw.active_page_id || raw.activePageId || "");
  let zoom = raw.zoom;
  if (zoom === "fit" || zoom === "fit-width") {
    /* ok */
  } else {
    const num = Number(zoom);
    zoom = Number.isFinite(num) && num > 0 ? num : "fit";
  }
  const scrollLeft = Math.max(0, Number(raw.scroll_left ?? raw.scrollLeft) || 0);
  const scrollTop = Math.max(0, Number(raw.scroll_top ?? raw.scrollTop) || 0);
  return { activePageId, zoom, scrollLeft, scrollTop };
}

/** Тело для API / project.json. */
export function editorSessionToWire(session) {
  const normalized = normalizeEditorSession(session);
  if (!normalized) return null;
  return {
    active_page_id: normalized.activePageId,
    zoom: normalized.zoom,
    scroll_left: normalized.scrollLeft,
    scroll_top: normalized.scrollTop,
  };
}

/** Масштаб «по ширине»: ширина кадра ≈ ширина stage. */
export function fitWidthScale(stageWidth, imageWidth, padding = 16) {
  const width = Math.max(1, Number(stageWidth) || 1);
  const natural = Math.max(1, Number(imageWidth) || 1);
  const pad = Math.max(0, Number(padding) || 0);
  return Math.max(0.01, (width - pad) / natural);
}

/** Выбрать active id: предпочесть preferred, иначе первый. */
export function resolveActivePageId(pages, preferredId) {
  const list = Array.isArray(pages) ? pages : [];
  const prefer = String(preferredId || "");
  if (prefer && list.some((page) => String(page.id) === prefer)) return prefer;
  return list[0] ? String(list[0].id) : "";
}

/** Режим штриха лассо по кнопке мыши: 0 → fill, 2 → erase_fill. */
export function polylineModeFromButton(button) {
  return Number(button) === 2 ? "erase_fill" : "fill";
}

/** Режим кисти по кнопке: 0 → paint, 2 → erase. */
export function brushModeFromButton(button) {
  return Number(button) === 2 ? "erase" : "paint";
}
