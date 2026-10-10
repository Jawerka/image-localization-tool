/** Чистая логика отложенной сессии правок (маска / стили) до «Готово». */

/** Нужно ли удерживать правку локально без save. */
export function shouldDeferEdit(optionDefer = false, alreadyDeferred = false) {
  return Boolean(optionDefer || alreadyDeferred);
}

/**
 * Baseline contentKey при входе в сессию.
 * Пустой baseline + новый ключ документа → запомнить ключ до правки.
 */
export function nextDeferredBaseline(currentBaseline, documentKeyBeforeEdit) {
  if (currentBaseline) return currentBaseline;
  return String(documentKeyBeforeEdit || "");
}

/** Сессия ещё pending после undo/redo. */
export function isDeferredPending(documentKey, baselineKey) {
  const baseline = String(baselineKey || "");
  if (!baseline) return false;
  return String(documentKey || "") !== baseline;
}

/** Нужен ли новый snapshot в past (anti-coalesce). */
export function shouldPushHistory(coalesceKey, previousCoalesceKey) {
  const key = String(coalesceKey || "");
  if (!key) return true;
  return key !== String(previousCoalesceKey || "");
}
