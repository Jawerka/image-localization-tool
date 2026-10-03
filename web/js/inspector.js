/* Инспектор региона и страницы. Текст уходит на сервер после паузы. */

import { fontList, getPage, pageAction, previewRegion, projectStyles, resetPage, sfxRestyle } from "./api.js";
import { confirm } from "./dialogs.js";
import {
  applyDetail,
  clearHistory,
  editDocument,
  findRegion,
  getState,
  patch,
  reloadDetail,
  sameId,
  selectRegion,
  setBanner,
  stageLabel,
  statusText,
  subscribe,
  whenSaved,
} from "./state.js";
import { mount as mountStyle, render as renderStyle } from "./style-panel.js";
import { setStylePreview, viewCenter } from "./viewer.js";
import { blankRegion, clampBox, nextRegionId } from "./state.js";

const TYPES = [
  ["dialogue", "диалог"],
  ["narration", "рассказ"],
  ["title", "заголовок"],
  ["sfx", "звук"],
  ["thought", "мысль"],
  ["caption", "надпись"],
];

const SLOW = new Set(["translation", "speaker", "font", "uppercase"]);

let list;
let facts;
let bar;
let tabsRoot;
let styleRoot;
let previewTimer = 0;
let previewKey = "";
let previewToken = 0;
let stylesProject = "";
let sfxNote = null;

export function init() {
  list = document.querySelector("[data-role='region-list']");
  facts = document.querySelector("[data-role='page-facts']");
  bar = document.querySelector("[data-role='inspector-bar']");
  tabsRoot = document.querySelector("[data-role='inspector']");
  tabsRoot.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => showTab(button.dataset.tab));
  });
  tabsRoot.querySelector("[role='tablist']").addEventListener("keydown", onTabKey);
  document.querySelector("[data-role='add-region']").addEventListener("click", addRegion);
  styleRoot = document.querySelector("[data-role='inspector-style']");
  mountStyle(styleRoot, {
    editDocument,
    getState,
    api: { previewRegion: retryPreview },
  });
  fontList().then((data) => patch({ fonts: (data && data.fonts) || [] })).catch(() => patch({ fonts: [] }));
  subscribe(render);
  render(getState());
}

function showTab(name) {
  tabsRoot.querySelectorAll("[data-tab]").forEach((button) => {
    const on = button.dataset.tab === name;
    button.setAttribute("aria-selected", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  });
  tabsRoot.querySelectorAll("[data-tabpanel]").forEach((panel) => {
    panel.hidden = panel.dataset.tabpanel !== name;
  });
}

function onTabKey(event) {
  const tabs = [...tabsRoot.querySelectorAll("[data-tab]")];
  const index = tabs.indexOf(document.activeElement);
  if (index < 0) return;
  let next = -1;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = tabs.length - 1;
  if (next < 0) return;
  event.preventDefault();
  tabs[next].focus();
  showTab(tabs[next].dataset.tab);
}

function render(state) {
  const page = state.pages.find((item) => item.id === state.activePageId);
  bar.hidden = !page;
  renderRegions(state, page);
  renderPage(state, page);
  watchStyles(state);
  watchPreview(state);
  renderStyle(state);
}

function renderRegions(state, page) {
  const focus = document.activeElement;
  const field = focus?.dataset?.field || "";
  const regionId = focus?.closest?.("[data-region-id]")?.dataset.regionId || "";
  const start = focus?.selectionStart;
  const end = focus?.selectionEnd;
  if (!page) {
    list.innerHTML = '<p class="inspector__empty">Откройте файлы или перетащите папку. Регионы появятся после распознавания.</p>';
    return;
  }
  const regions = state.document?.regions || [];
  if (!state.document) {
    list.innerHTML = '<p class="inspector__empty">Страница открывается.</p>';
    return;
  }
  if (!regions.length) {
    list.innerHTML = '<p class="inspector__empty">Нет регионов. Добавьте рамку или запустите перевод.</p>';
    return;
  }
  list.innerHTML = regions.map((region, index) => card(region, index, state)).join("");
  list.querySelectorAll("[data-region-id]").forEach((cardNode) => {
    cardNode.querySelector(".region-card__head")?.addEventListener("click", () => {
      selectRegion(cardNode.dataset.regionId);
    });
  });
  list.querySelectorAll("[data-field]").forEach((input) => {
    const eventName = input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input";
    input.addEventListener(eventName, () => onField(input));
  });
  list.querySelectorAll("[data-region-action]").forEach((button) => {
    button.addEventListener("click", () => onAction(button));
  });
  if (regionId && field) {
    const next = list.querySelector(`[data-region-id="${cssEscape(regionId)}"] [data-field="${field}"]`);
    if (next) {
      next.focus();
      if (typeof start === "number" && next.setSelectionRange) next.setSelectionRange(start, end);
    }
  }
}

function card(region, index, state) {
  const selected = sameId(region.id, state.selectedRegionId);
  const classes = ["region-card"];
  if (selected) classes.push("region-card--selected");
  if (region.skip) classes.push("region-card--skipped");
  if (region.overflow) classes.push("region-card--overflow");
  if ((region.type || region.block_type) === "sfx") classes.push("region-card--sfx");
  const title = region.text || region.translation || "Пустой регион";
  const flags = [];
  if (region.skip) flags.push("Пропущен");
  if (region.overflow) flags.push("Не влез");
  const flag = flags.length ? `<span class="region-card__flag">${region.overflow ? icon("warning") : ""}${escapeText(flags.join(" · "))}</span>` : "";
  const head = `<button type="button" class="region-card__head"><span class="region-card__num">${index + 1}</span><span class="region-card__title">${escapeText(title)}</span>${flag}</button>`;
  if (!selected) {
    const muted = [region.translation, typeLabel(region.type), region.speaker].filter(Boolean).join(" · ");
    return `<article class="${classes.join(" ")}" data-region-id="${escapeAttr(region.id)}">${head}${muted ? `<p class="muted">${escapeText(muted)}</p>` : ""}</article>`;
  }
  const pending = state.pendingAction && sameId(state.pendingAction.regionId, region.id)
    ? `<p class="warn-line">${icon("warning")}<span>Ждёт сервер LLM</span></p>`
    : "";
  return `<article class="${classes.join(" ")}" data-region-id="${escapeAttr(region.id)}" aria-current="true">${head}${pending}
    <label class="field" for="orig-${escapeAttr(region.id)}">Оригинал
      <textarea id="orig-${escapeAttr(region.id)}" class="textarea" lang="${escapeAttr(state.settings.source_lang)}" rows="2" readonly>${escapeText(region.text)}</textarea>
    </label>
    <label class="field" for="tr-${escapeAttr(region.id)}">Перевод
      <textarea id="tr-${escapeAttr(region.id)}" class="textarea" lang="${escapeAttr(state.settings.target_lang)}" rows="2" data-field="translation">${escapeText(region.translation)}</textarea>
    </label>
    <div class="region-card__row">
      <label class="field" for="type-${escapeAttr(region.id)}">Тип
        <select id="type-${escapeAttr(region.id)}" class="select" data-field="type">${typeOptions(region.type)}</select>
      </label>
      <label class="field" for="speaker-${escapeAttr(region.id)}">Говорящий
        <input id="speaker-${escapeAttr(region.id)}" class="input" type="text" data-field="speaker" value="${escapeAttr(region.speaker)}">
      </label>
    </div>
    ${sfxNoteHtml(region)}
    <div class="region-card__actions">
      <button type="button" class="btn btn-accent" data-region-action="recognize">Распознать</button>
      <button type="button" class="btn btn-accent" data-region-action="retranslate">Перевести заново</button>
      <button type="button" class="btn btn-accent" data-region-action="shorten">Сократить</button>
      <button type="button" class="btn btn-ghost" data-region-action="skip" aria-pressed="${region.skip ? "true" : "false"}">Не переводить</button>
      ${(region.type || region.block_type) === "sfx" ? sfxButton(region) : ""}
      <button type="button" class="btn btn-ghost" data-region-action="delete">${icon("delete")}Удалить</button>
    </div>
    <div class="region-card__row">
      <label class="field" for="size-${escapeAttr(region.id)}">Кегль
        <input id="size-${escapeAttr(region.id)}" class="input" type="number" min="0" data-field="font" value="${Number(region.style?.font_size_override) || 0}">
      </label>
      <label class="choice">
        <input data-field="uppercase" type="checkbox"${region.style?.uppercase ? " checked" : ""}>
        ПРОПИСНЫЕ
      </label>
    </div>
  </article>`;
}

function renderPage(state, page) {
  if (!page) {
    facts.innerHTML = '<p class="inspector__empty">Нет открытой страницы.</p>';
    return;
  }
  const document = state.document;
  const rows = [
    ["Статус", statusText(page)],
    ["OCR", document?.ocr_engine || "—"],
    ["Перевод", document?.translator_engine || "—"],
    ["Очистка", cleanLabel(state.settings.inpainter_backend)],
    ["Устройство", state.device || "—"],
  ];
  const timings = document?.timings || {};
  Object.keys(timings).forEach((key) => {
    rows.push([stageLabel(key) || key, formatSeconds(timings[key])]);
  });
  const warnings = []
    .concat(document?.warnings || [])
    .concat(page.error ? [page.error] : []);
  const warningHtml = warnings.map((item) => `<p class="warn-line">${icon("warning")}<span>${escapeText(item)}</span></p>`).join("");
  facts.innerHTML = `<dl class="kv">${rows.map(([name, value]) => `<dt>${escapeText(name)}</dt><dd>${escapeText(value)}</dd>`).join("")}</dl>
    ${warningHtml}
    <div class="region-card__actions">
      <button type="button" class="btn btn-accent" data-page-action="retranslate">Перевести заново</button>
      <button type="button" class="btn btn-ghost" data-page-action="reset">Сбросить правки</button>
    </div>`;
  facts.querySelector("[data-page-action='retranslate']").addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("ilt-translate-page"));
  });
  facts.querySelector("[data-page-action='reset']").addEventListener("click", reset);
}

async function reset() {
  const pageId = getState().activePageId;
  if (!pageId) return;
  const ok = await confirm({
    title: "Сбросить правки?",
    text: "Ручные правки этой страницы будут заменены результатом пайплайна. Это нельзя отменить.",
    ok: "Сбросить",
    cancel: "Отмена",
  });
  if (!ok) return;
  await resetPage(pageId);
  clearHistory(pageId);
  reloadDetail(pageId);
}

function addRegion() {
  const center = viewCenter();
  let created = 0;
  editDocument((document) => {
    created = nextRegionId(document);
    const box = clampBox([center.x - 40, center.y - 20, 80, 40], center.w, center.h);
    const region = blankRegion(created, box);
    region.order = document.regions.length;
    document.regions.push(region);
  });
  if (!getState().showBoxes) patch({ showBoxes: true });
  selectRegion(created);
}

function onField(input) {
  const cardNode = input.closest("[data-region-id]");
  if (!cardNode) return;
  const id = cardNode.dataset.regionId;
  const field = input.dataset.field;
  const slow = SLOW.has(field);
  editDocument((document) => {
    const region = findRegion(document, id);
    if (!region) return;
    region.edited = true;
    region.style = { ...(region.style || {}) };
    if (field === "translation") region.translation = input.value;
    if (field === "speaker") region.speaker = input.value;
    if (field === "type") {
      region.type = input.value;
      region.block_type = input.value;
    }
    if (field === "font") {
      const value = input.value === "" ? 0 : Number(input.value);
      region.style.font_size_override = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
    }
    if (field === "uppercase") region.style.uppercase = input.checked;
  }, { debounce: slow ? 500 : 0, coalesce: slow ? `${field}:${id}` : "" });
}

async function onAction(button) {
  const cardNode = button.closest("[data-region-id]");
  const id = cardNode?.dataset.regionId;
  const action = button.dataset.regionAction;
  const pageId = getState().activePageId;
  if (!id || !pageId) return;
  if (action === "delete") {
    editDocument((document) => {
      document.regions = document.regions.filter((region) => !sameId(region.id, id));
    });
    selectRegion(null);
    return;
  }
  if (action === "skip") {
    editDocument((document) => {
      const region = findRegion(document, id);
      if (!region) return;
      region.skip = !region.skip;
      region.edited = true;
    });
    return;
  }
  if (action === "sfx") {
    await restyleSfx(pageId, id, button);
    return;
  }
  patch({ pendingAction: { pageId, regionId: id, action } });
  try {
    await pageAction(pageId, action, id);
  } catch (error) {
    patch({ pendingAction: null });
    document.dispatchEvent(new CustomEvent("ilt-banner", { detail: { id: "action", text: error.message || "Не удалось выполнить действие" } }));
  }
}

function typeOptions(current) {
  const options = TYPES.slice();
  if (current && !options.some((item) => item[0] === current)) options.push([current, current]);
  return options.map(([value, label]) => `<option value="${escapeAttr(value)}"${value === current ? " selected" : ""}>${escapeText(label)}</option>`).join("");
}

function typeLabel(type) {
  const found = TYPES.find((item) => item[0] === type);
  return found ? found[1] : (type || "");
}

function cleanLabel(value) {
  if (value === "opencv" || value === "fill") return "Заливка";
  if (value === "lama") return "LaMa";
  return value || "—";
}

function formatSeconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "—");
  return `${number.toFixed(1).replace(".", ",")} с`;
}

function icon(id) {
  return `<svg class="icon" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
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

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(String(value));
  return String(value);
}

function sfxButton(region) {
  const busy = sfxNote && sameId(sfxNote.id, region.id) && sfxNote.status === "loading";
  return `<button type="button" class="btn btn-accent" data-region-action="sfx"${busy ? " disabled" : ""}>Подобрать стиль заново</button>`;
}

function sfxNoteHtml(region) {
  if (!sfxNote || !sameId(sfxNote.id, region.id) || (region.type || region.block_type) !== "sfx") return "";
  if (sfxNote.status === "loading") return `<p class="field-hint" role="status">Подбираем стиль звука</p>`;
  if (sfxNote.status === "error") return `<p class="sfx-reason" role="alert">${icon("error")}<span>${escapeText(sfxNote.message || "Не удалось подобрать стиль")}</span></p>`;
  return `<p class="field-hint">${icon("info")}Звук остаётся в рисованном стиле букв, не шрифтом баллона.</p>`;
}

async function restyleSfx(pageId, regionId, button) {
  sfxNote = { id: regionId, status: "loading", message: "" };
  if (button) button.disabled = true;
  render(getState());
  try {
    await whenSaved(pageId);
    await sfxRestyle(pageId, regionId);
    const data = await getPage(pageId);
    applyDetail(pageId, data, false, true);
    sfxNote = { id: regionId, status: "ready", message: "" };
  } catch (error) {
    sfxNote = { id: regionId, status: "error", message: error.message || "Не удалось подобрать стиль" };
    setBanner("sfx", { tone: "warning", text: sfxNote.message });
  }
  render(getState());
}

function watchStyles(state) {
  const id = state.project && state.project.id ? String(state.project.id) : "";
  if (id === stylesProject) return;
  stylesProject = id;
  if (!id) {
    patch({ styleLibrary: [] });
    return;
  }
  projectStyles().then((data) => {
    if (!getState().project || String(getState().project.id) !== id) return;
    patch({ styleLibrary: (data && data.styles) || [] });
  }).catch(() => {});
}

function watchPreview(state) {
  const region = findRegion(state.document, state.selectedRegionId);
  const key = region ? `${state.activePageId}|${region.id}|${JSON.stringify(region.style || {})}` : "";
  if (key === previewKey) return;
  previewKey = key;
  window.clearTimeout(previewTimer);
  if (!region || !state.activePageId) {
    setStylePreview(null);
    if (state.stylePreview && state.stylePreview.status !== "idle") {
      patch({ stylePreview: { status: "idle", message: "" } });
    }
    return;
  }
  const pageId = state.activePageId;
  const regionId = region.id;
  patch({ stylePreview: { status: "loading", message: "Обновляем предпросмотр" } });
  previewTimer = window.setTimeout(() => runPreview(pageId, regionId, key), 400);
}

function retryPreview(regionId) {
  const state = getState();
  if (!state.activePageId) return;
  const region = findRegion(state.document, regionId);
  const key = region ? `${state.activePageId}|${region.id}|${JSON.stringify(region.style || {})}|retry` : "";
  previewKey = key;
  patch({ stylePreview: { status: "loading", message: "Обновляем предпросмотр" } });
  runPreview(state.activePageId, regionId, key);
}

async function runPreview(pageId, regionId, key) {
  const token = ++previewToken;
  try {
    const result = await previewRegion(pageId, regionId);
    if (token !== previewToken || key !== previewKey) {
      URL.revokeObjectURL(result.url);
      return;
    }
    setStylePreview(result);
    patch({ stylePreview: { status: "ready", message: "" } });
  } catch (error) {
    if (token !== previewToken || key !== previewKey) return;
    setStylePreview(null);
    patch({ stylePreview: { status: "error", message: error.message || "Не удалось обновить предпросмотр" } });
  }
}
