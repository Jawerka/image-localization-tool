/** Чистая логика: когда инспектору можно не трогать DOM карточек. */

/**
 * Fingerprint содержимого списка регионов (то, что рисует карточки).
 * Игнорирует job/progress/busy и прочий шум state.
 */
export function inspectorContentKey(state = {}) {
  const doc = state.document;
  const regions = Array.isArray(doc?.regions) ? doc.regions : [];
  const fonts = Array.isArray(state.fonts) ? state.fonts.map((font) => String(font?.id ?? "")).join(",") : "";
  const styles = Array.isArray(state.styleLibrary)
    ? state.styleLibrary.map((item) => String(item?.name || "")).join(",")
    : "";
  const pending = state.pendingAction
    ? `${state.pendingAction.regionId || ""}:${state.pendingAction.action || ""}`
    : "";
  const regionBits = regions.map((region) => [
    region.id,
    region.text,
    region.translation,
    region.translation_locked ? 1 : 0,
    region.type || region.block_type,
    region.speaker,
    region.skip ? 1 : 0,
    region.overflow ? 1 : 0,
    region.edited ? 1 : 0,
    JSON.stringify(region.style || {}),
    JSON.stringify(region.bbox || []),
  ].join("\x1f")).join("\x1e");
  return [
    state.activePageId || "",
    state.selectedRegionId || "",
    doc ? "1" : "0",
    regions.length,
    fonts,
    styles,
    pending,
    regionBits,
  ].join("|");
}

/**
 * Фокус в поле ввода/select (не в заголовке карточки).
 * Open details сами по себе rebuild не блокируют — их open восстанавливается.
 */
export function inspectorInteractionActive(root, activeElement = null) {
  if (!root) return false;
  const focus = activeElement || (typeof document !== "undefined" ? document.activeElement : null);
  if (!focus || !root.contains(focus)) return false;
  if (focus.closest?.(".region-card__head")) return false;
  const tag = String(focus.tagName || "").toUpperCase();
  if (tag === "SELECT" || tag === "TEXTAREA" || tag === "INPUT") return true;
  if (focus.isContentEditable) return true;
  return false;
}

/**
 * Пропустить полный rebuild списка — только при полностью совпадающем ключе.
 * Смена selectedRegionId меняет ключ → rebuild обязателен (раскрытие карточки).
 */
export function shouldSkipInspectorRebuild(prevKey, nextKey) {
  if (!nextKey) return false;
  return prevKey === nextKey;
}

/** Снимок open у всех details в карточках. */
export function captureAllDetailsOpen(root) {
  const map = {};
  if (!root) return map;
  root.querySelectorAll("[data-region-id]").forEach((card) => {
    const id = String(card.dataset.regionId || "");
    if (!id) return;
    const warp = card.querySelector("details.region-card__warp");
    const styles = card.querySelector("details.region-card__styles");
    map[id] = {
      warp: warp ? Boolean(warp.open) : null,
      styles: styles ? Boolean(styles.open) : null,
    };
  });
  return map;
}

export function detailsOpenFromMap(map, regionId, key, fallbackOpen) {
  const entry = map && map[String(regionId)];
  if (entry && typeof entry[key] === "boolean") return entry[key] ? " open" : "";
  return fallbackOpen ? " open" : "";
}
