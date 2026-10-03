/* Диалоги: экспорт, горячие клавиши, подтверждение, модель, ошибка воркера. */

import { dialogDirectory, dialogLog, exportPages, glossary, putGlossary } from "./api.js";
import { render as renderGlossary } from "./glossary-panel.js";
import { getState, isReadyStatus, plural, setBanner } from "./state.js";

let overlay;
let lastFocus = null;
let confirmResolve = null;
let pickResolve = null;
let dirReady = false;
let glossaryRows = null;
let glossaryError = "";

export function init() {
  overlay = document.querySelector("[data-role='modals']");
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeTop();
  });
  overlay.addEventListener("keydown", trap);
  overlay.querySelectorAll("[data-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => closeTop());
  });
  document.querySelector("[data-role='confirm-ok']").addEventListener("click", () => finishConfirm(true));
  document.querySelector("[data-role='confirm-cancel']").addEventListener("click", () => finishConfirm(false));
  document.querySelector("[data-role='export-browse']").addEventListener("click", browseExport);
  document.querySelector("[data-role='export-go']").addEventListener("click", runExport);
  document.querySelector("[data-role='export-quality']").addEventListener("input", (event) => {
    document.querySelector("[data-role='export-quality-value']").textContent = event.target.value;
  });
  document.querySelector("[data-role='model-choose']").addEventListener("click", () => finishPick(true));
  document.querySelector("[data-role='worker-log']").addEventListener("click", () => {
    dialogLog().catch((error) => setBanner("log", { text: error.message || "Не удалось открыть лог" }));
  });
  document.querySelector("[data-role='hotkeys-close']").addEventListener("click", () => closeTop());
}

export function isAnyOpen() {
  return Boolean(overlay && !overlay.hidden);
}

export function current() {
  const dialog = overlay?.querySelector("[data-dialog]:not([hidden])");
  return dialog ? dialog.dataset.dialog : "";
}

export function closeTop() {
  if (!isAnyOpen()) return false;
  const name = current();
  if (name === "confirm") finishConfirm(false);
  else if (name === "models") finishPick(false);
  else hide();
  return true;
}

export function confirm(options) {
  document.querySelector("[data-role='confirm-title']").textContent = options.title;
  document.querySelector("[data-role='confirm-text']").textContent = options.text;
  document.querySelector("[data-role='confirm-ok']").textContent = options.ok || "ОК";
  document.querySelector("[data-role='confirm-cancel']").textContent = options.cancel || "Отмена";
  show("confirm");
  document.querySelector("[data-role='confirm-cancel']").focus();
  return new Promise((resolve) => {
    confirmResolve = resolve;
  });
}

export function openGlossary() {
  glossaryRows = null;
  glossaryError = "";
  show("glossary");
  paintGlossary();
  glossary()
    .then((data) => {
      if (current() !== "glossary") return;
      glossaryRows = Array.isArray(data && data.glossary) ? data.glossary : [];
      glossaryError = "";
      paintGlossary();
    })
    .catch((error) => {
      if (current() !== "glossary") return;
      glossaryRows = [];
      glossaryError = error.message || "Не удалось прочитать глоссарий";
      paintGlossary();
    });
}

function paintGlossary() {
  const root = document.querySelector("[data-role='glossary-root']");
  renderGlossary(root, glossaryRows, {
    error: glossaryError,
    onChange(rows) {
      glossaryRows = rows;
    },
    onSave() {
      saveGlossary();
    },
    onRetry() {
      openGlossary();
    },
  });
}

async function saveGlossary() {
  try {
    const data = await putGlossary(glossaryRows || []);
    glossaryRows = Array.isArray(data && data.glossary) ? data.glossary : (glossaryRows || []);
    glossaryError = "";
    paintGlossary();
  } catch (error) {
    glossaryError = error.message || "Не удалось сохранить";
    paintGlossary();
  }
}

export function openHotkeys() {
  if (current() === "hotkeys") {
    closeTop();
    return;
  }
  show("hotkeys");
}

export function openExport() {
  const state = getState();
  if (!state.pages.length) return;
  dirReady = false;
  const ready = state.pages.filter((page) => isReadyStatus(page.status)).length;
  const selected = state.selectedPageIds.length;
  setChoice("export-which", "all", `Все (${state.pages.length})`);
  setChoice("export-which", "ready", `Только готовые (${ready})`);
  setChoice("export-which", "selected", `Выбранные (${selected})`);
  const readyInput = overlay.querySelector("input[name='export-which'][value='ready']");
  const selectedInput = overlay.querySelector("input[name='export-which'][value='selected']");
  readyInput.disabled = ready === 0;
  selectedInput.disabled = selected === 0;
  const preset = ready ? "ready" : "all";
  overlay.querySelector(`input[name='export-which'][value='${preset}']`).checked = true;
  const settings = state.settings;
  overlay.querySelector("[data-role='export-format']").value = settings.export_format === "jpg" ? "jpg" : "png";
  const quality = overlay.querySelector("[data-role='export-quality']");
  quality.value = String(settings.export_jpeg_quality || 90);
  document.querySelector("[data-role='export-quality-value']").textContent = quality.value;
  const conflict = settings.export_conflict === "overwrite" || settings.export_conflict === "skip" ? settings.export_conflict : "rename";
  overlay.querySelector(`input[name='export-clash'][value='${conflict}']`).checked = true;
  const contentInput = overlay.querySelector("input[name='export-content'][value='result']");
  if (contentInput) contentInput.checked = true;
  const folder = overlay.querySelector("[data-role='export-dir']");
  folder.value = "";
  folder.placeholder = "Папка будет выбрана перед записью";
  show("export");
}

export function openModelPick(models, onPick) {
  const host = document.querySelector("[data-role='model-list-dialog']");
  const list = Array.isArray(models) ? models : [];
  if (!list.length) {
    host.innerHTML = "<p>Сервер не вернул модели.</p>";
  } else {
    host.innerHTML = list.map((item, index) => modelRow(item, index)).join("");
  }
  show("models");
  pickResolve = onPick;
}

export function openWorker(message) {
  document.querySelector("[data-role='worker-text']").textContent = message || "Воркер перезапускался чаще трёх раз в минуту и остановлен.";
  show("worker");
}

async function browseExport() {
  try {
    const data = await dialogDirectory();
    if (!accepted(data)) return;
    dirReady = true;
    document.querySelector("[data-role='export-dir']").value = data.path || data.directory || data.folder || "Папка выбрана";
  } catch (error) {
    setBanner("export", { text: error.message || "Не удалось выбрать папку" });
  }
}

async function runExport() {
  if (!dirReady) {
    try {
      const data = await dialogDirectory();
      if (!accepted(data)) return;
      dirReady = true;
      document.querySelector("[data-role='export-dir']").value = data.path || data.directory || data.folder || "Папка выбрана";
    } catch (error) {
      setBanner("export", { text: error.message || "Не удалось выбрать папку" });
      return;
    }
  }
  const pageIds = exportIds();
  if (!pageIds.length) {
    setBanner("export", { text: "Нет страниц для экспорта" });
    return;
  }
  const format = document.querySelector("[data-role='export-format']").value === "jpg" ? "jpg" : "png";
  const quality = Number(document.querySelector("[data-role='export-quality']").value) || 90;
  const conflictInput = overlay.querySelector("input[name='export-clash']:checked");
  const conflict = conflictInput ? conflictInput.value : "rename";
  const contentInput = overlay.querySelector("input[name='export-content']:checked");
  const content = contentInput && (contentInput.value === "clean" || contentInput.value === "both")
    ? contentInput.value
    : "result";
  try {
    const result = await exportPages({
      page_ids: pageIds,
      format,
      jpeg_quality: quality,
      conflict,
      content,
    });
    hide();
    const count = Number(result?.count ?? result?.saved ?? result?.paths?.length ?? pageIds.length);
    const errors = Array.isArray(result?.errors) ? result.errors.filter(Boolean) : [];
    const text = `Сохранено ${count} ${plural(count, "страница", "страницы", "страниц")}`;
    setBanner("export", {
      text: errors.length ? `${text}. ${errors[0]}` : text,
      actions: [{ id: "reveal", label: "Открыть папку" }],
    });
  } catch (error) {
    setBanner("export", { text: error.message || "Не удалось экспортировать" });
  }
}

function exportIds() {
  const state = getState();
  const which = overlay.querySelector("input[name='export-which']:checked")?.value || "all";
  if (which === "selected") return state.selectedPageIds.slice();
  if (which === "ready") return state.pages.filter((page) => isReadyStatus(page.status)).map((page) => page.id);
  return state.pages.map((page) => page.id);
}

function accepted(data) {
  if (!data) return false;
  if (data.cancelled || data.canceled || data.ok === false) return false;
  return true;
}

function setChoice(name, value, label) {
  const input = overlay.querySelector(`input[name='${name}'][value='${value}']`);
  if (input && input.parentElement) {
    const text = input.parentElement.querySelector("span");
    if (text) text.textContent = label;
  }
}

function modelRow(item, index) {
  const id = typeof item === "string" ? item : (item.id || item.name || `model-${index}`);
  const label = typeof item === "string" ? item : (item.name || item.id || id);
  const vision = typeof item === "object" && item ? item.vision : null;
  let badge = "";
  if (vision === true) badge = `<span class="badge badge--ok"><svg class="icon" aria-hidden="true"><use href="icons/icons.svg#check"></use></svg> принимает картинки</span>`;
  if (vision === false) badge = `<span class="badge badge--warn"><svg class="icon" aria-hidden="true"><use href="icons/icons.svg#warning"></use></svg> без картинок</span>`;
  return `<label class="model-pick__item"><input type="radio" name="model-pick" value="${escapeAttr(id)}"${index === 0 ? " checked" : ""}><span>${escapeText(label)}</span>${badge}</label>`;
}

function finishConfirm(value) {
  const resolve = confirmResolve;
  confirmResolve = null;
  hide();
  if (resolve) resolve(value);
}

function finishPick(ok) {
  const resolve = pickResolve;
  pickResolve = null;
  const selected = overlay.querySelector("input[name='model-pick']:checked");
  hide();
  if (resolve) resolve(ok && selected ? selected.value : "");
}

function show(name) {
  lastFocus = document.activeElement;
  overlay.hidden = false;
  overlay.querySelectorAll("[data-dialog]").forEach((dialog) => {
    dialog.hidden = dialog.dataset.dialog !== name;
  });
  setInert(true);
  const dialog = overlay.querySelector(`[data-dialog='${name}']`);
  dialog.focus();
}

function hide() {
  overlay.hidden = true;
  overlay.querySelectorAll("[data-dialog]").forEach((dialog) => {
    dialog.hidden = true;
  });
  setInert(false);
  if (lastFocus && lastFocus.focus) lastFocus.focus();
  lastFocus = null;
}

function setInert(on) {
  document.querySelector("[data-role='shell']")?.toggleAttribute("inert", on);
  document.querySelectorAll("[data-role='screen-settings'], [data-role='screen-wizard']").forEach((node) => {
    if (!node.hidden) node.toggleAttribute("inert", on);
  });
}

function trap(event) {
  if (event.key !== "Tab" || overlay.hidden) return;
  const dialog = overlay.querySelector("[data-dialog]:not([hidden])");
  if (!dialog) return;
  const items = [...dialog.querySelectorAll("button, input, select, textarea, a[href]")].filter((node) => {
    if (node.disabled || node.hidden) return false;
    if (node.closest("[hidden]")) return false;
    return true;
  });
  if (!items.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeText(value);
}
