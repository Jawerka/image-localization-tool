/** Плавающий чип «Готово»: clamp/snap и drag по горизонтали. */

export const APPLY_CHIP_DRAG_THRESHOLD_PX = 6;
export const APPLY_CHIP_CENTER_SNAP_PX = 32;
export const APPLY_CHIP_STORAGE_KEY = "ilt.apply-edits.offset";

/**
 * Ограничить смещение центра чипа относительно центра хоста.
 * @param {number} offsetPx смещение центра чипа от центра хоста (+: вправо)
 * @param {number} hostWidth
 * @param {number} chipWidth
 * @param {number} padding
 */
export function clampApplyChipOffset(offsetPx, hostWidth, chipWidth, padding = 8) {
  const host = Math.max(0, Number(hostWidth) || 0);
  const chip = Math.max(0, Number(chipWidth) || 0);
  const pad = Math.max(0, Number(padding) || 0);
  const max = Math.max(0, (host - chip) / 2 - pad);
  const value = Number(offsetPx) || 0;
  return Math.max(-max, Math.min(max, value));
}

/** Soft-snap к центру, если |offset| меньше порога. */
export function snapApplyChipOffset(offsetPx, thresholdPx = APPLY_CHIP_CENTER_SNAP_PX) {
  const value = Number(offsetPx) || 0;
  const threshold = Math.max(0, Number(thresholdPx) || 0);
  return Math.abs(value) <= threshold ? 0 : value;
}

/** Движение больше порога → drag, не click. */
export function isApplyChipDrag(movedPx, thresholdPx = APPLY_CHIP_DRAG_THRESHOLD_PX) {
  return Math.abs(Number(movedPx) || 0) > Math.max(0, Number(thresholdPx) || 0);
}

export function readStoredApplyChipOffset(storage = globalThis.sessionStorage) {
  try {
    const raw = storage?.getItem?.(APPLY_CHIP_STORAGE_KEY);
    if (raw == null || raw === "") return 0;
    const value = Number(raw);
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

export function writeStoredApplyChipOffset(offsetPx, storage = globalThis.sessionStorage) {
  try {
    storage?.setItem?.(APPLY_CHIP_STORAGE_KEY, String(Number(offsetPx) || 0));
  } catch {
    /* ignore quota / private mode */
  }
}

/**
 * Привязать drag к кнопке внутри хоста.
 * @param {{ chip: HTMLElement, host: HTMLElement, onCommit: () => void }} options
 */
export function bindApplyChipDrag({ chip, host, onCommit }) {
  if (!chip || !host) return () => {};

  let offset = readStoredApplyChipOffset();
  let pointerId = null;
  let startX = 0;
  let originOffset = 0;
  let moved = 0;
  let dragging = false;
  let suppressClick = false;
  let clickTimer = 0;

  function layout() {
    const hostRect = host.getBoundingClientRect();
    const chipRect = chip.getBoundingClientRect();
    offset = clampApplyChipOffset(offset, hostRect.width, chipRect.width || chip.offsetWidth);
    chip.style.setProperty("--apply-offset", `${offset}px`);
    chip.classList.toggle("is-centered", offset === 0);
  }

  function setOffset(next, { persist = false, snap = false } = {}) {
    const hostRect = host.getBoundingClientRect();
    const chipWidth = chip.getBoundingClientRect().width || chip.offsetWidth;
    let value = clampApplyChipOffset(next, hostRect.width, chipWidth);
    if (snap) value = snapApplyChipOffset(value);
    offset = value;
    chip.style.setProperty("--apply-offset", `${offset}px`);
    chip.classList.toggle("is-centered", offset === 0);
    chip.classList.toggle("is-dragging", dragging);
    if (persist) writeStoredApplyChipOffset(offset);
  }

  function onPointerDown(event) {
    if (event.button !== 0) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    originOffset = offset;
    moved = 0;
    dragging = false;
    suppressClick = false;
    chip.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event) {
    if (pointerId == null || event.pointerId !== pointerId) return;
    const dx = event.clientX - startX;
    moved = Math.max(moved, Math.abs(dx));
    if (!dragging && isApplyChipDrag(moved)) {
      dragging = true;
      chip.classList.add("is-dragging");
    }
    if (!dragging) return;
    event.preventDefault();
    setOffset(originOffset + dx);
  }

  function onPointerUp(event) {
    if (pointerId == null || event.pointerId !== pointerId) return;
    const wasDragging = dragging;
    pointerId = null;
    dragging = false;
    chip.classList.remove("is-dragging");
    if (wasDragging) {
      suppressClick = true;
      setOffset(offset, { persist: true, snap: true });
    }
  }

  function onClick(event) {
    if (suppressClick || isApplyChipDrag(moved)) {
      event.preventDefault();
      event.stopPropagation();
      suppressClick = false;
      moved = 0;
      return;
    }
    /* Отложить commit, чтобы dblclick успел отменить и только центрировать. */
    window.clearTimeout(clickTimer);
    clickTimer = window.setTimeout(() => {
      clickTimer = 0;
      onCommit?.();
    }, 280);
  }

  function onDblClick(event) {
    event.preventDefault();
    window.clearTimeout(clickTimer);
    clickTimer = 0;
    setOffset(0, { persist: true });
  }

  chip.addEventListener("pointerdown", onPointerDown);
  chip.addEventListener("pointermove", onPointerMove);
  chip.addEventListener("pointerup", onPointerUp);
  chip.addEventListener("pointercancel", onPointerUp);
  chip.addEventListener("click", onClick);
  chip.addEventListener("dblclick", onDblClick);
  window.addEventListener("resize", layout);
  const visibility = new MutationObserver(() => {
    if (!chip.hidden) layout();
  });
  visibility.observe(chip, { attributes: true, attributeFilter: ["hidden"] });

  layout();

  return () => {
    window.clearTimeout(clickTimer);
    visibility.disconnect();
    chip.removeEventListener("pointerdown", onPointerDown);
    chip.removeEventListener("pointermove", onPointerMove);
    chip.removeEventListener("pointerup", onPointerUp);
    chip.removeEventListener("pointercancel", onPointerUp);
    chip.removeEventListener("click", onClick);
    chip.removeEventListener("dblclick", onDblClick);
    window.removeEventListener("resize", layout);
  };
}

/** Инициализация чипа в DOM. */
export function initApplyChip({ onCommit } = {}) {
  const chip = document.querySelector("[data-role='apply-edits']");
  const host = document.querySelector("[data-role='stage-host']");
  if (!chip || !host) return;
  bindApplyChipDrag({ chip, host, onCommit });
}
