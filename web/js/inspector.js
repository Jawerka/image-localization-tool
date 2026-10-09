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

const SLOW = new Set(["translation", "speaker", "uppercase"]);

let list;
let facts;
let bar;
let tabsRoot;
let fontDraft = null;
let rebuilding = false;
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
  const tabs = [...tabsRoot.querySelectorAll("[data-tab]")].filter((tab) => !tab.hidden);
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
}

function renderRegions(state, page) {
  const focus = document.activeElement;
  const field = focus?.dataset?.field || "";
  const regionId = focus?.closest?.("[data-region-id]")?.dataset.regionId || "";
  const start = focus?.selectionStart;
  const end = focus?.selectionEnd;
  const scroll = list.scrollTop;
  rebuilding = true;
  try {
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
      if (input.dataset.field === "font") bindFontField(input);
    });
    list.querySelectorAll("[data-font-step]").forEach((button) => {
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => onFontStep(button));
    });
    list.querySelectorAll("[data-region-action]").forEach((button) => {
      button.addEventListener("click", () => onAction(button));
    });
    list.querySelectorAll("[data-ink]").forEach((button) => {
      button.addEventListener("click", () => onInk(button));
    });
    list.querySelectorAll("[data-card-warp]").forEach((button) => {
      button.addEventListener("click", () => onCardWarp(button));
    });
    list.querySelectorAll("[data-font-nav]").forEach((button) => {
      button.addEventListener("click", () => onFontNav(button));
    });
    if (regionId && field) {
      const next = list.querySelector(`[data-region-id="${cssEscape(regionId)}"] [data-field="${field}"]`);
      if (next) {
        next.focus({ preventScroll: true });
        if (typeof start === "number" && next.setSelectionRange) next.setSelectionRange(start, end);
      }
    }
  } finally {
    list.scrollTop = scroll;
    rebuilding = false;
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
      <button type="button" class="btn btn-ghost" data-region-action="reset-style">Сбросить стили</button>
      <button type="button" class="btn btn-ghost" data-region-action="delete">${icon("delete")}Удалить</button>
    </div>
    <div class="region-card__row">
      ${fontMarkup(region, state)}
      <label class="choice">
        <input data-field="uppercase" type="checkbox"${region.style?.uppercase ? " checked" : ""}>
        ПРОПИСНЫЕ
      </label>
    </div>
    ${inkToggle(region)}
    ${cardStyleMarkup(region, state)}
  </article>`;
}

function renderPage(state, page) {
  const scroll = facts.scrollTop;
  if (!page) {
    facts.innerHTML = '<p class="inspector__empty">Нет открытой страницы.</p>';
    facts.scrollTop = scroll;
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
  facts.scrollTop = scroll;
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
  if (rebuilding || !input.isConnected) return;
  const cardNode = input.closest("[data-region-id]");
  if (!cardNode) return;
  const id = cardNode.dataset.regionId;
  const field = input.dataset.field;
  if (field === "font") {
    onFontInput(input, id);
    return;
  }
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
    if (field === "uppercase") region.style.uppercase = input.checked;
    if (field === "font_id") region.style.font_id = input.value || "";
    if (field === "fill_rgb") {
      region.style.fill_rgb = hexToRgb(input.value);
      region.style.fill_locked = true;
    }
    if (field === "stroke_rgb") {
      region.style.stroke_rgb = hexToRgb(input.value);
      region.style.stroke_mode = "custom";
    }
    if (field === "warp_bend") {
      const bend = Number(input.value);
      region.style.warp = { ...(region.style.warp || { kind: "none", quad: null, mesh: null }) };
      region.style.warp.bend = Number.isFinite(bend) ? bend : 0;
      const output = input.parentElement?.querySelector("output");
      if (output) output.textContent = Number(region.style.warp.bend).toFixed(2);
    }
  }, { debounce: slow ? 500 : 0, coalesce: slow ? `${field}:${id}` : "" });
}

function bindFontField(input) {
  const id = input.closest("[data-region-id]")?.dataset.regionId;
  input.addEventListener("keydown", (event) => onFontKey(event, input, id));
  input.addEventListener("blur", (event) => {
    if (rebuilding || !input.isConnected) return;
    const next = event.relatedTarget;
    if (next && next.closest && next.closest("[data-role='font-field']")) return;
    commitFont(id);
  });
}

function onFontInput(input, id) {
  const raw = String(input.value || "");
  const digits = raw.replace(/\D/g, "");
  if (digits !== raw) {
    const cursor = input.selectionStart || 0;
    const before = raw.slice(0, cursor).replace(/\D/g, "").length;
    input.value = digits;
    if (input.setSelectionRange) input.setSelectionRange(before, before);
  }
  keepDraft(id, input.value);
  paintFontHint(input);
  syncFontButtons(input);
  armFontCommit(id);
}

function onFontKey(event, input, id) {
  if (event.key === "Enter") {
    event.preventDefault();
    commitFont(id);
  }
  if (event.key === "Escape") {
    event.preventDefault();
    cancelFontDraft(input, id);
  }
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    stepFont(input, id, event.key === "ArrowUp" ? 1 : -1, event.shiftKey);
  }
}

function onFontStep(button) {
  const input = button.closest("[data-role='font-field']")?.querySelector("[data-field='font']");
  const id = button.closest("[data-region-id]")?.dataset.regionId;
  if (!input || !id) return;
  stepFont(input, id, Number(button.dataset.fontStep) || 0, false);
  input.focus();
}

function stepFont(input, id, direction, shift) {
  const state = getState();
  const bounds = fontBounds(state);
  const region = findRegion(state.document, id);
  const next = Math.min(bounds.max, Math.max(bounds.min, fontBase(input, region, bounds) + direction * (shift ? 10 : 1)));
  input.value = String(next);
  keepDraft(id, input.value);
  paintFontHint(input);
  syncFontButtons(input);
  armFontCommit(id);
}

function keepDraft(regionId, text) {
  if (fontDraft && !sameId(fontDraft.regionId, regionId)) window.clearTimeout(fontDraft.timer);
  fontDraft = {
    regionId,
    text,
    timer: fontDraft && sameId(fontDraft.regionId, regionId) ? fontDraft.timer : 0,
  };
}

function armFontCommit(regionId) {
  if (!fontDraft || !sameId(fontDraft.regionId, regionId)) return;
  window.clearTimeout(fontDraft.timer);
  fontDraft.timer = window.setTimeout(() => commitFont(regionId), 1000);
}

function commitFont(regionId) {
  if (rebuilding || !fontDraft || !sameId(fontDraft.regionId, regionId)) return;
  const text = fontDraft.text;
  window.clearTimeout(fontDraft.timer);
  fontDraft = null;
  const value = clampFont(text, getState());
  editDocument((document) => {
    const region = findRegion(document, regionId);
    if (!region) return;
    region.edited = true;
    region.style = { ...(region.style || {}) };
    region.style.font_size_override = value;
  }, { debounce: 0, coalesce: `font:${regionId}` });
}

function cancelFontDraft(input, regionId) {
  if (fontDraft && sameId(fontDraft.regionId, regionId)) {
    window.clearTimeout(fontDraft.timer);
    fontDraft = null;
  }
  const region = findRegion(getState().document, regionId);
  input.value = fontFieldValue(region);
  paintFontHint(input);
  syncFontButtons(input);
}

function fontMarkup(region, state) {
  const bounds = fontBounds(state);
  const draft = fontDraft && sameId(fontDraft.regionId, region.id) ? fontDraft.text : null;
  const value = draft == null ? fontFieldValue(region) : draft;
  const numeric = Number(String(value).replace(/\D/g, "")) || 0;
  const auto = Number(region.style?.font_size) || 0;
  const shown = numeric || auto || bounds.min;
  const placeholder = auto > 0 ? `авто · ${auto}` : "авто";
  const warn = numeric > 0 && (numeric < bounds.min || numeric > bounds.max);
  const hint = warn
    ? `от ${bounds.min} до ${bounds.max}, пусто — авто. Будет ${numeric < bounds.min ? bounds.min : bounds.max}`
    : `от ${bounds.min} до ${bounds.max}, пусто — авто`;
  return `<label class="field" for="size-${escapeAttr(region.id)}">Кегль
    <div class="num-field" data-role="font-field">
      <button type="button" class="btn btn-ghost num-field__btn" data-font-step="-1" aria-label="Уменьшить кегль"${shown <= bounds.min ? " disabled" : ""}>−</button>
      <input id="size-${escapeAttr(region.id)}" class="input num-field__input" type="text" inputmode="numeric" autocomplete="off" placeholder="${escapeAttr(placeholder)}" data-field="font" value="${escapeAttr(value)}">
      <button type="button" class="btn btn-ghost num-field__btn" data-font-step="1" aria-label="Увеличить кегль"${shown >= bounds.max ? " disabled" : ""}>+</button>
    </div>
    <span class="field-hint${warn ? " field-hint--warn" : ""}">${escapeText(hint)}</span>
  </label>`;
}

function paintFontHint(input) {
  const hint = input.closest(".field")?.querySelector(".field-hint");
  if (!hint) return;
  const bounds = fontBounds(getState());
  const numeric = Number(String(input.value || "").replace(/\D/g, "")) || 0;
  const warn = numeric > 0 && (numeric < bounds.min || numeric > bounds.max);
  hint.classList.toggle("field-hint--warn", warn);
  hint.textContent = warn
    ? `от ${bounds.min} до ${bounds.max}, пусто — авто. Будет ${numeric < bounds.min ? bounds.min : bounds.max}`
    : `от ${bounds.min} до ${bounds.max}, пусто — авто`;
}

function syncFontButtons(input) {
  const field = input.closest("[data-role='font-field']");
  if (!field) return;
  const bounds = fontBounds(getState());
  const region = findRegion(getState().document, input.closest("[data-region-id]")?.dataset.regionId);
  const shown = Number(String(input.value || "").replace(/\D/g, "")) || Number(region?.style?.font_size) || bounds.min;
  const minus = field.querySelector("[data-font-step='-1']");
  const plus = field.querySelector("[data-font-step='1']");
  if (minus) minus.disabled = shown <= bounds.min;
  if (plus) plus.disabled = shown >= bounds.max;
}

function fontBase(input, region, bounds) {
  const digits = String(input.value || "").replace(/\D/g, "");
  if (digits) return Number(digits);
  const auto = Number(region?.style?.font_size) || 0;
  return auto > 0 ? auto : bounds.min;
}

function clampFont(text, state) {
  const digits = String(text || "").replace(/\D/g, "");
  if (!digits) return 0;
  const bounds = fontBounds(state);
  return Math.min(bounds.max, Math.max(bounds.min, Math.round(Number(digits))));
}

function fontFieldValue(region) {
  const size = Number(region?.style?.font_size_override) || 0;
  return size > 0 ? String(size) : "";
}

function fontBounds(state) {
  const min = fontBound(state, "min_font_size", 10);
  return { min, max: Math.max(min, fontBound(state, "max_font_size", 128)) };
}

function fontBound(state, key, fallback) {
  const value = Number(state.settings?.[key]);
  return Number.isFinite(value) && value > 0 ? Math.round(value) : fallback;
}

function inkSide(fill) {
  const rgb = Array.isArray(fill) ? fill : [0, 0, 0];
  const mean = (Number(rgb[0]) + Number(rgb[1]) + Number(rgb[2])) / 3;
  return mean > 127.5 ? "white" : "black";
}

function inkToggle(region) {
  const side = inkSide(region.style && region.style.fill_rgb);
  const button = (value, label) => {
    const pressed = side === value ? "true" : "false";
    return `<button type="button" class="btn btn-ghost" data-ink="${value}" aria-pressed="${pressed}">${label}</button>`;
  };
  return `<div class="ink-toggle" role="group" aria-label="Цвет текста">${button("black", "Чёрный")}${button("white", "Белый")}</div>`;
}

function rgbToHex(rgb) {
  const channels = Array.isArray(rgb) ? rgb : [0, 0, 0];
  const to = (value) => Math.max(0, Math.min(255, Math.round(Number(value) || 0))).toString(16).padStart(2, "0");
  return `#${to(channels[0])}${to(channels[1])}${to(channels[2])}`;
}

function hexToRgb(value) {
  const text = String(value || "").replace("#", "");
  if (text.length !== 6) return [0, 0, 0];
  return [0, 2, 4].map((offset) => Number.parseInt(text.slice(offset, offset + 2), 16) || 0);
}

const CARD_WARPS = [
  ["none", "Нет"],
  ["arc-up", "Дугой вверх"],
  ["arc-down", "Дугой вниз"],
  ["ring", "Кольцо"],
  ["wave", "Волна"],
  ["flag", "Флаг"],
  ["perspective", "Перспектива"],
  ["mesh", "Сетка"],
];

function cardStyleMarkup(region, state) {
  const fonts = Array.isArray(state.fonts) ? state.fonts : [];
  const fontId = region.style?.font_id || "";
  const fontOptions = [`<option value="">По умолчанию</option>`]
    .concat(fonts.map((font) => {
      const id = font && font.id != null ? String(font.id) : "";
      const label = (font && (font.family || font.id)) || id;
      const selected = id === String(fontId) ? " selected" : "";
      return `<option value="${escapeAttr(id)}"${selected}>${escapeText(label)}</option>`;
    }))
    .join("");
  const fill = rgbToHex(region.style?.fill_rgb);
  const stroke = region.style?.stroke_rgb ? rgbToHex(region.style.stroke_rgb) : "#000000";
  const warp = region.style?.warp || {};
  const bend = Number(warp.bend);
  const bendValue = Number.isFinite(bend) ? bend : 0;
  const choice = warpChoice(warp);
  const presets = CARD_WARPS.map(([id, label]) => {
    const pressed = choice === id ? "true" : "false";
    return `<button type="button" class="btn btn-ghost" data-card-warp="${id}" aria-pressed="${pressed}">${escapeText(label)}</button>`;
  }).join("");
  return `<div class="region-card__style">
    <label class="field" for="font-id-${escapeAttr(region.id)}">Шрифт
      <div class="num-field" data-role="font-family-field">
        <button type="button" class="btn btn-ghost num-field__btn" data-font-nav="-1" aria-label="Предыдущий шрифт">←</button>
        <select id="font-id-${escapeAttr(region.id)}" class="select" data-field="font_id">${fontOptions}</select>
        <button type="button" class="btn btn-ghost num-field__btn" data-font-nav="1" aria-label="Следующий шрифт">→</button>
      </div>
    </label>
    <div class="region-card__row style-colors">
      <label class="field" for="fill-${escapeAttr(region.id)}">Заливка
        <input id="fill-${escapeAttr(region.id)}" type="color" data-field="fill_rgb" value="${escapeAttr(fill)}">
      </label>
      <label class="field" for="stroke-${escapeAttr(region.id)}">Обводка
        <input id="stroke-${escapeAttr(region.id)}" type="color" data-field="stroke_rgb" value="${escapeAttr(stroke)}">
      </label>
    </div>
    <details class="region-card__warp" open>
      <summary>Искривление</summary>
      <div class="warp-presets" role="group" aria-label="Вид искривления">${presets}</div>
      <label class="field" for="bend-${escapeAttr(region.id)}">Изгиб
        <span class="style-range">
          <input id="bend-${escapeAttr(region.id)}" type="range" min="-1" max="1" step="0.05" data-field="warp_bend" value="${escapeAttr(String(bendValue))}">
          <output for="bend-${escapeAttr(region.id)}">${bendValue.toFixed(2)}</output>
        </span>
      </label>
    </details>
  </div>`;
}

function warpChoice(warp) {
  const kind = warp && warp.kind ? warp.kind : "none";
  const bend = Number(warp && warp.bend);
  const value = Number.isFinite(bend) ? bend : 0;
  if (kind === "arc") return value >= 0 ? "arc-up" : "arc-down";
  if (kind === "wave") {
    if (Math.abs(value) < 0.25 && value !== 0) return "flag";
    return "wave";
  }
  if (kind === "ring" || kind === "perspective" || kind === "mesh" || kind === "none") return kind;
  return "none";
}

function defaultQuadPoints(w, h) {
  return [[0, 0], [w, 0], [w, h], [0, h]];
}

function defaultMeshPoints(w, h) {
  const points = [];
  for (let row = 0; row < 4; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      points.push([(col * w) / 3, (row * h) / 3]);
    }
  }
  return points;
}

function applyCardWarp(region, preset) {
  const style = region.style || (region.style = {});
  const warp = { ...(style.warp || { kind: "none", bend: 0, quad: null, mesh: null }) };
  const box = region.bbox || [0, 0, 100, 100];
  const bw = Math.max(1, Number(box[2]) || 100);
  const bh = Math.max(1, Number(box[3]) || 100);
  const bend = Number(warp.bend);
  const current = Number.isFinite(bend) ? bend : 0;
  if (preset === "none") {
    warp.kind = "none";
    warp.bend = 0;
    warp.quad = null;
    warp.mesh = null;
  } else if (preset === "arc-up") {
    warp.kind = "arc";
    warp.bend = 0.35;
  } else if (preset === "arc-down") {
    warp.kind = "arc";
    warp.bend = -0.35;
  } else if (preset === "ring") {
    warp.kind = "ring";
    warp.bend = current === 0 ? 0.35 : current;
  } else if (preset === "wave") {
    warp.kind = "wave";
    warp.bend = 0.35;
  } else if (preset === "flag") {
    warp.kind = "wave";
    warp.bend = 0.15;
  } else if (preset === "perspective") {
    warp.kind = "perspective";
    warp.quad = Array.isArray(warp.quad) && warp.quad.length === 4 ? warp.quad : defaultQuadPoints(bw, bh);
    warp.mesh = null;
  } else if (preset === "mesh") {
    warp.kind = "mesh";
    warp.mesh = Array.isArray(warp.mesh) && warp.mesh.length === 16 ? warp.mesh : defaultMeshPoints(bw, bh);
    warp.quad = null;
  }
  style.warp = warp;
}

function onInk(button) {
  const cardNode = button.closest("[data-region-id]");
  const id = cardNode?.dataset.regionId;
  const ink = button.dataset.ink;
  if (!id || (ink !== "black" && ink !== "white")) return;
  editDocument((document) => {
    const region = findRegion(document, id);
    if (!region) return;
    region.edited = true;
    region.style = { ...(region.style || {}) };
    region.style.fill_rgb = ink === "white" ? [255, 255, 255] : [0, 0, 0];
    region.style.fill_locked = true;
  });
}

function onCardWarp(button) {
  const cardNode = button.closest("[data-region-id]");
  const id = cardNode?.dataset.regionId;
  const preset = button.dataset.cardWarp;
  if (!id || !preset) return;
  editDocument((document) => {
    const region = findRegion(document, id);
    if (!region) return;
    region.edited = true;
    region.style = { ...(region.style || {}) };
    applyCardWarp(region, preset);
  });
}

function onFontNav(button) {
  const cardNode = button.closest("[data-region-id]");
  const select = cardNode?.querySelector("[data-field='font_id']");
  const id = cardNode?.dataset.regionId;
  const step = Number(button.dataset.fontNav) || 0;
  if (!select || !id || !step) return;
  const options = [...select.options];
  if (!options.length) return;
  const index = Math.max(0, options.findIndex((item) => item.selected));
  const next = (index + step + options.length) % options.length;
  select.selectedIndex = next;
  onField(select);
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
  if (action === "reset-style") {
    editDocument((document) => {
      const region = findRegion(document, id);
      if (!region) return;
      region.edited = true;
      region.style = { ...(region.style || {}) };
      region.style.rotation = 0;
      const warp = { ...(region.style.warp || {}) };
      warp.kind = "none";
      warp.bend = 0;
      warp.quad = null;
      warp.mesh = null;
      region.style.warp = warp;
    });
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
