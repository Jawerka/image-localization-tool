/* Горячие клавиши. Однобуквенные — только вне полей и если их не выключили. */

import { getState } from "./state.js";

let actions = {};
let space = false;

export function isSpaceDown() {
  return space;
}

export function isTyping(target) {
  const element = target || document.activeElement;
  if (!element) return false;
  if (element.isContentEditable) return true;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export function install(next) {
  actions = next;
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("keyup", onKeyUp, true);
  window.addEventListener("blur", () => releaseSpace());
}

function releaseSpace() {
  if (!space) return;
  space = false;
  actions.space?.(false);
}

function browserBlocked(event) {
  const key = event.key.toLowerCase();
  const reload = event.key === "F5" || (event.ctrlKey && key === "r");
  const print = event.ctrlKey && key === "p";
  const find = event.ctrlKey && key === "f";
  if (!reload && !print && !find) return false;
  if (reload && getState().offline) return false;
  event.preventDefault();
  event.stopPropagation();
  return true;
}

function inPageList(target) {
  return Boolean(target && target.closest && target.closest("[data-role='page-list']"));
}

function onKey(event) {
  if (browserBlocked(event)) return;
  if (event.isComposing || event.key === "Process") return;

  const key = event.key;
  const low = key.toLowerCase();
  const target = event.target;

  if (key === "F1") {
    event.preventDefault();
    actions.hotkeys?.();
    return;
  }
  if (key === "Escape") {
    event.preventDefault();
    actions.escape?.();
    return;
  }

  if (actions.modal?.()) return;

  const settingsOpen = Boolean(actions.settingsOpen?.());
  const typing = isTyping(target);

  if (key === " " && !typing && !settingsOpen && !inPageList(target) && target?.tagName !== "BUTTON") {
    event.preventDefault();
    if (!event.repeat) {
      space = true;
      actions.space?.(true);
    }
    return;
  }

  if (event.ctrlKey && !event.altKey && !event.metaKey) {
    if (low === "o" && !event.shiftKey) {
      event.preventDefault();
      actions.openFiles?.();
      return;
    }
    if (low === "o" && event.shiftKey) {
      event.preventDefault();
      actions.openFolder?.();
      return;
    }
    if (low === "e" && !event.shiftKey) {
      event.preventDefault();
      actions.export?.();
      return;
    }
    if (key === "," || event.code === "Comma") {
      event.preventDefault();
      actions.settings?.();
      return;
    }
    if (key === "Enter") {
      event.preventDefault();
      if (event.shiftKey) actions.translateAll?.();
      else actions.translatePage?.();
      return;
    }
    if (low === "z" && !event.shiftKey && !typing) {
      event.preventDefault();
      actions.undo?.();
      return;
    }
    if (low === "y" && !event.shiftKey && !typing) {
      event.preventDefault();
      actions.redo?.();
      return;
    }
    if (event.shiftKey && low === "c") {
      if (typing) return;
      event.preventDefault();
      actions.copyStyle?.();
      return;
    }
    if (event.shiftKey && low === "v") {
      if (typing) return;
      event.preventDefault();
      actions.pasteStyle?.();
      return;
    }
    if (!event.shiftKey && (event.code === "Digit0" || key === "0")) {
      event.preventDefault();
      actions.zoomFit?.();
      return;
    }
    if (!event.shiftKey && (event.code === "Digit1" || key === "1")) {
      event.preventDefault();
      actions.zoom100?.();
      return;
    }
  }

  if (settingsOpen || typing) return;
  if (inPageList(target) && (key === "ArrowUp" || key === "ArrowDown" || key === "Home" || key === "End")) return;

  if (key === "PageDown") {
    event.preventDefault();
    actions.page?.(1);
    return;
  }
  if (key === "PageUp") {
    event.preventDefault();
    actions.page?.(-1);
    return;
  }
  if (!event.ctrlKey && !event.altKey && !event.metaKey && (key === "n" || key === "N" || event.code === "KeyN")) {
    event.preventDefault();
    actions.nextProblem?.();
    return;
  }

  if (key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown") {
    if (ownsArrows(target)) return;
    if (getState().selectedRegionId == null) return;
    event.preventDefault();
    actions.nudge?.(key, { shift: event.shiftKey, alt: event.altKey });
    return;
  }

  if ((key === "Delete" || key === "Del") && !inPageList(target)) {
    event.preventDefault();
    actions.deleteRegion?.();
    return;
  }

  if (key === "[" || event.code === "BracketLeft") {
    event.preventDefault();
    actions.brush?.(-1);
    return;
  }
  if (key === "]" || event.code === "BracketRight") {
    event.preventDefault();
    actions.brush?.(1);
    return;
  }

  if (!singleKeys()) return;
  const toolByCode = { KeyV: "select", KeyR: "region", KeyB: "brush", KeyE: "eraser" };
  const viewByCode = { Digit1: "original", Digit2: "result", Digit3: "compare" };
  if (toolByCode[event.code]) {
    event.preventDefault();
    actions.tool?.(toolByCode[event.code]);
    return;
  }
  if (viewByCode[event.code]) {
    event.preventDefault();
    actions.view?.(viewByCode[event.code]);
    return;
  }
  if (event.code === "KeyM") {
    event.preventDefault();
    actions.mask?.();
    return;
  }
  if (event.code === "KeyL") {
    event.preventDefault();
    actions.boxes?.();
  }
}

function onKeyUp(event) {
  if (event.key === " " || event.code === "Space") releaseSpace();
}

function ownsArrows(target) {
  if (!target || !target.closest) return false;
  return Boolean(target.closest("[role='radiogroup'], [role='tablist'], [role='menu'], [data-role='context-menu'], .settings, .wizard, .dialog"));
}

function singleKeys() {
  return Boolean(getState().settings && getState().settings.single_key_shortcuts);
}
