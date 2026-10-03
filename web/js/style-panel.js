/* Панель стиля региона: шрифт, заливка, обводка и искривление. */

const FAV_KEY = "ilt-font-favorites";

const WARP_PRESETS = [
  ["none", "Нет"],
  ["arc-up", "Дугой вверх"],
  ["arc-down", "Дугой вниз"],
  ["ring", "Кольцо"],
  ["wave", "Волна"],
  ["flag", "Флаг"],
  ["perspective", "Перспектива"],
  ["mesh", "Сетка"],
];

const STROKE_MODES = [
  ["auto", "Авто"],
  ["none", "Нет"],
  ["custom", "Своя"],
];

const DEFAULT_CHIPS = [
  { name: "Диалог" },
  { name: "Крик" },
  { name: "SFX" },
];

const KEEP_FIELDS = ["font_size", "alignment", "uppercase", "line_height"];

let panel = null;
let deps = null;
let fontQuery = "";
let shown = null;
let liveKey = "";
let lastPreviewBusy = false;
const bound = new WeakSet();

export function mount(root, nextDeps) {
  panel = root;
  deps = nextDeps || {};
  if (!panel || bound.has(panel)) return;
  bound.add(panel);
  panel.addEventListener("click", onClick);
  panel.addEventListener("input", onInput);
  panel.addEventListener("change", onChange);
  panel.addEventListener("keydown", onKeyDown);
}

export function render(state) {
  if (!panel) return;
  shown = state && typeof state === "object" ? state : {};
  const region = selectedRegion(shown);
  const mode = viewMode(shown, region);
  const busy = previewBusy(shown);
  if (busy) panel.setAttribute("aria-busy", "true");
  else panel.removeAttribute("aria-busy");
  const key = viewKey(shown, region, mode);
  // Ползунок и цвет не пересобираем: иначе жест обрывается на каждом input.
  if (key === liveKey && shouldPatch(mode)) {
    syncLive(shown, region, mode);
    paintPreviewNote(busy);
    lastPreviewBusy = busy;
    return;
  }
  if (key === liveKey && busy !== lastPreviewBusy && panel.querySelector(".style-state:not([hidden])")) {
    paintPreviewNote(busy);
    lastPreviewBusy = busy;
    return;
  }
  lastPreviewBusy = busy;
  const focus = captureFocus();
  panel.innerHTML = frame(mode, bodyFor(shown, region, mode));
  liveKey = key;
  restoreFocus(focus);
}

function onClick(event) {
  const target = eventTarget(event);
  if (!target || target.closest("[disabled]")) return;
  const favorite = target.closest(".style-font__fav");
  if (favorite) {
    if (favorite.disabled) return;
    toggleFavorite(favorite.getAttribute("data-font-id"));
    return;
  }
  const warp = target.closest("[data-warp]");
  if (warp) {
    if (warp.disabled) return;
    const preset = warp.getAttribute("data-warp");
    editSelected((style) => applyPreset(style, preset));
    render(currentState());
    return;
  }
  const modeButton = target.closest("[data-stroke-mode]");
  if (modeButton) {
    if (modeButton.disabled) return;
    const mode = modeButton.getAttribute("data-stroke-mode");
    if (mode !== "auto" && mode !== "none" && mode !== "custom") return;
    editSelected((style) => {
      style.stroke_mode = mode;
    });
    render(currentState());
    return;
  }
  const chip = target.closest("[data-chip]");
  if (chip) {
    if (chip.disabled) return;
    applyChip(Number(chip.getAttribute("data-chip")));
    render(currentState());
    return;
  }
  if (target.closest("[data-action='retry']")) retryPreview();
}

function onInput(event) {
  const input = event.target;
  if (!input || !input.dataset) return;
  const keep = input.dataset.keep;
  if (!keep || input.disabled) return;
  if (keep === "search") {
    fontQuery = input.value;
    render(currentState());
    return;
  }
  const value = input.value;
  if (keep === "rotation" && !isFinishedNumber(value)) return;
  const live = { coalesce: `style:${keep}`, debounce: 200 };
  if (keep === "fill") {
    editSelected((style) => {
      style.fill_rgb = hexToRgb(value);
      style.fill_locked = false;
    }, live);
  } else if (keep === "stroke") {
    editSelected((style) => {
      style.stroke_rgb = hexToRgb(value);
    }, live);
  } else if (keep === "stroke-width") {
    editSelected((style) => writeWidth(style, value), live);
  } else if (keep === "rotation") {
    editSelected((style) => writeRotation(style, value), live);
  } else if (keep === "bend") {
    editSelected((style) => writeBend(style, value), live);
  } else {
    return;
  }
  render(currentState());
}

function onChange(event) {
  const input = event.target;
  if (!input || input.disabled) return;
  if (input.name === "font") {
    const value = input.value;
    editSelected((style) => {
      style.font_id = fontIdFromList(value);
    });
    render(currentState());
    return;
  }
  if (input.dataset && input.dataset.keep === "rotation" && !isFinishedNumber(input.value)) {
    editSelected((style) => writeRotation(style, "0"));
    render(currentState());
  }
}

function onKeyDown(event) {
  const target = eventTarget(event);
  if (!target || target.getAttribute("role") !== "radio" || target.disabled) return;
  const group = target.closest("[role='radiogroup']");
  if (!group) return;
  let dir = 0;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") dir = 1;
  else if (event.key === "ArrowLeft" || event.key === "ArrowUp") dir = -1;
  else return;
  const buttons = [...group.querySelectorAll("[role='radio']:not([disabled])")];
  const index = buttons.indexOf(target);
  if (index < 0) return;
  event.preventDefault();
  const next = buttons[(index + dir + buttons.length) % buttons.length];
  const warp = next.getAttribute("data-warp");
  const mode = next.getAttribute("data-stroke-mode");
  if (warp) {
    editSelected((style) => applyPreset(style, warp));
  } else if (mode === "auto" || mode === "none" || mode === "custom") {
    editSelected((style) => {
      style.stroke_mode = mode;
    });
  } else {
    return;
  }
  render(currentState());
  const visible = panel && panel.querySelector(".style-state:not([hidden])");
  const selector = warp ? `[data-warp="${escapeCss(warp)}"]` : `[data-stroke-mode="${escapeCss(mode)}"]`;
  const focused = visible && visible.querySelector(selector);
  if (focused) focused.focus();
}

function editSelected(mutate, options) {
  if (!deps || typeof deps.editDocument !== "function") return;
  const state = currentState();
  const selectedId = state.selectedRegionId;
  if (selectedId == null || selectedId === "") return;
  deps.editDocument((document) => {
    if (!document || !Array.isArray(document.regions)) return;
    const region = document.regions.find((item) => item && item.id == selectedId);
    if (!region) return;
    mutate(ensureStyle(region));
  }, options);
}

function applyChip(index) {
  const chips = chipsOf(currentState());
  const chip = chips[index];
  if (!chip || !isPlain(chip.style)) return;
  let incoming;
  try {
    incoming = JSON.parse(JSON.stringify(chip.style));
  } catch (err) {
    return;
  }
  editSelected((style) => {
    Object.assign(style, incoming);
  });
}

function retryPreview() {
  const api = deps && deps.api;
  if (!api || typeof api.previewRegion !== "function") return;
  const selectedId = currentState().selectedRegionId;
  if (selectedId == null || selectedId === "") return;
  api.previewRegion(selectedId);
}

function toggleFavorite(fontId) {
  if (fontId == null) return;
  const id = String(fontId);
  const current = readFavorites();
  const has = current.some((item) => String(item) === id);
  const next = has ? current.filter((item) => String(item) !== id) : current.concat(id);
  writeFavorites(next);
  render(currentState());
}

function currentState() {
  try {
    if (deps && typeof deps.getState === "function") {
      const live = deps.getState();
      if (live && typeof live === "object") return live;
    }
  } catch (err) {
    /* состояние недоступно */
  }
  return shown || {};
}

function selectedRegion(state) {
  const regions = state && state.document && Array.isArray(state.document.regions) ? state.document.regions : null;
  if (!regions) return null;
  const selectedId = state.selectedRegionId;
  if (selectedId == null || selectedId === "") return null;
  return regions.find((region) => region && region.id == selectedId) || null;
}

function viewMode(state, region) {
  if (!region) return "empty";
  const status = state.stylePreview && state.stylePreview.status;
  if (status === "error") return "error";
  return "ready";
}

function previewBusy(state) {
  return Boolean(state && state.stylePreview && state.stylePreview.status === "loading");
}

function paintPreviewNote(busy) {
  if (!panel) return;
  const note = panel.querySelector(".style-status");
  if (!note) return;
  note.hidden = !busy;
  note.textContent = busy ? "Обновляем предпросмотр" : "";
}

function regionNumber(state, region) {
  const regions = state.document.regions;
  const index = regions.indexOf(region);
  return index >= 0 ? index + 1 : region.id;
}

function frame(mode, body) {
  // Четыре состояния в панели. Видно одно; у остальных только data-state и hidden,
  // без второй формы: одинаковый name=font склеил бы радиокнопки.
  const names = ["empty", "loading", "error", "ready"];
  const visible = `<div class="style-state" data-state="${mode}">${body}</div>`;
  const hidden = names
    .filter((name) => name !== mode)
    .map((name) => `<div class="style-state" data-state="${name}" hidden></div>`)
    .join("");
  return visible + hidden;
}

function bodyFor(state, region, mode) {
  if (mode === "empty") {
    return `<h2>Регион не выбран</h2><p class="muted">Выберите регион на странице, чтобы задать шрифт и искривление.</p>`;
  }
  if (mode === "loading") {
    return `<h2>Обновляем предпросмотр</h2><p class="style-status" role="status">Обновляем предпросмотр</p>${controls(state, region, false)}`;
  }
  if (mode === "error") {
    return `<h2>Не удалось обновить предпросмотр</h2><p class="style-fail">${icon("error")}<span>${escapeText(failMessage(state))}</span></p><button type="button" class="btn btn-accent" data-action="retry">Повторить</button>${controls(state, region, false)}`;
  }
  return `<h2>Стиль региона ${escapeText(regionNumber(state, region))}</h2><p class="style-status" role="status" hidden></p>${controls(state, region, false)}`;
}

function failMessage(state) {
  const message = state.stylePreview && state.stylePreview.message;
  const text = String(message || "").trim();
  return text || "Не удалось нарисовать образец.";
}

function controls(state, region, locked) {
  const style = viewStyle(region);
  const fonts = fontsOf(state);
  const off = locked ? " disabled" : "";
  const busy = locked ? " style-sample--busy" : "";
  return `<label class="field" for="font-search">Найти шрифт
      <input id="font-search" class="input" type="search" autocomplete="off" data-keep="search" value="${escapeAttr(fontQuery)}"${off}>
    </label>
    <fieldset${off}>
      <legend>Шрифт</legend>
      ${fontBlock(fonts, style, off)}
    </fieldset>
    <p class="field__label" id="sample-label">Образец</p>
    <p class="style-sample${busy}" lang="ru" style="${escapeAttr(sampleCss(style, fonts))}">${escapeText(sampleText(region))}</p>
    <div class="region-card__row style-colors">
      <label class="field" for="fill-color">Заливка
        <input id="fill-color" type="color" data-keep="fill" value="${rgbToHex(style.fill_rgb)}"${off}>
      </label>
      <label class="field" for="stroke-color">Обводка
        <input id="stroke-color" type="color" data-keep="stroke" value="${style.stroke_rgb ? rgbToHex(style.stroke_rgb) : "#000000"}"${off}>
      </label>
    </div>
    <label class="field" for="stroke-width">Толщина обводки
      <span class="style-range">
        <input id="stroke-width" type="range" min="0" max="20" step="1" data-keep="stroke-width" value="${widthShown(style.stroke_width)}"${off}>
        <output for="stroke-width">${widthShown(style.stroke_width)}</output>
      </span>
    </label>
    <div class="field">
      <span class="field__label" id="stroke-mode-label">Режим обводки</span>
      <div role="radiogroup" aria-labelledby="stroke-mode-label">
        ${STROKE_MODES.map(([id, label]) => radioButton("data-stroke-mode", id, label, style.stroke_mode === id, off)).join("")}
      </div>
    </div>
    <label class="field" for="angle">Угол
      <input id="angle" class="input" type="number" step="1" data-keep="rotation" value="${escapeAttr(shownNumber(style.rotation))}" aria-describedby="angle-hint"${off}>
    </label>
    <p class="field-hint" id="angle-hint">градусы, против часовой стрелки</p>
    <div class="field">
      <span class="field__label" id="warp-label">Искривление</span>
      <div class="style-warp" role="radiogroup" aria-label="Искривление" aria-labelledby="warp-label">
        ${WARP_PRESETS.map(([id, label]) => radioButton("data-warp", id, label, warpChoice(style.warp) === id, off)).join("")}
      </div>
    </div>
    <label class="field" for="bend">Изгиб
      <span class="style-range">
        <input id="bend" type="range" min="-1" max="1" step="0.01" data-keep="bend" value="${bendShown(style.warp.bend)}"${off}>
        <output for="bend">${bendShown(style.warp.bend).toFixed(2)}</output>
      </span>
    </label>
    <div class="field">
      <span class="field__label" id="lib-label">Стили проекта</span>
      <div class="style-chips" role="group" aria-label="Стили проекта" aria-labelledby="lib-label">
        ${chipButtons(chipsOf(state), style, off)}
      </div>
    </div>
    <p class="field-hint" id="style-copy-hint">${icon("info")}<kbd class="kbd">Ctrl+Shift+C</kbd> копирует стиль региона, <kbd class="kbd">Ctrl+Shift+V</kbd> вставляет его в выбранный.</p>`;
}

function radioButton(attr, id, label, checked, off) {
  const tab = checked ? "0" : "-1";
  return `<button type="button" class="btn" role="radio" ${attr}="${escapeAttr(id)}" aria-checked="${checked ? "true" : "false"}" tabindex="${tab}"${off}>${escapeText(label)}</button>`;
}

function fontBlock(fonts, style, off) {
  const favorites = new Set(readFavorites().map((item) => String(item)));
  const query = fontQuery.trim().toLowerCase();
  const visible = orderFonts(fonts, favorites).filter((font) => {
    if (!query) return true;
    return String(font.family || "").toLowerCase().includes(query);
  });
  if (!visible.length) return `<p class="muted">Шрифты не найдены</p>`;
  return `<ul class="style-font-list">${visible.map((font, index) => fontRow(font, style, favorites, off, index)).join("")}</ul>`;
}

function fontRow(font, style, favorites, off, index) {
  const family = font.family ? String(font.family) : String(font.id);
  const inputId = `style-font-${index}`;
  const checked = font.id == style.font_id ? " checked" : "";
  const pressed = favorites.has(String(font.id));
  const familyCss = cssFamily(family);
  const spanStyle = familyCss ? ` style="font-family: ${escapeAttr(familyCss)}"` : "";
  return `<li class="style-font-row" data-name="${escapeAttr(family)}">
      <label class="choice">
        <input id="${inputId}" type="radio" name="font" value="${escapeAttr(font.id)}"${checked}${off}>
        <span${spanStyle}>${escapeText(family)}</span>
      </label>
      <button type="button" class="btn btn-ghost style-font__fav" data-font-id="${escapeAttr(font.id)}" aria-pressed="${pressed ? "true" : "false"}" aria-label="${escapeAttr(`Избранное: ${family}`)}"${off}><span aria-hidden="true">★</span> Избранное</button>
    </li>`;
}

function chipButtons(chips, style, off) {
  return chips.map((chip, index) => {
    if (!chip || !chip.name) return "";
    const pressed = chipMatches(style, chip);
    return `<button type="button" class="btn" data-chip="${index}" aria-pressed="${pressed ? "true" : "false"}"${off}>${escapeText(chip.name)}</button>`;
  }).join("");
}

function chipMatches(style, chip) {
  if (!isPlain(chip.style)) return false;
  const chipWarp = isPlain(chip.style.warp) ? chip.style.warp : {};
  const fontId = style.font_id == null ? "" : style.font_id;
  const chipFont = chip.style.font_id == null ? "" : chip.style.font_id;
  const mode = style.stroke_mode || "auto";
  const chipMode = chip.style.stroke_mode || "auto";
  const kind = style.warp && style.warp.kind ? style.warp.kind : "none";
  const chipKind = chipWarp.kind || "none";
  return fontId == chipFont && mode == chipMode && kind == chipKind;
}

function fontsOf(state) {
  if (!state || !Array.isArray(state.fonts)) return [];
  return state.fonts.filter((font) => font && font.id != null);
}

function orderFonts(fonts, favorites) {
  return fonts
    .map((font, index) => ({ font, index, fav: favorites.has(String(font.id)) }))
    .sort((a, b) => (a.fav === b.fav ? a.index - b.index : a.fav ? -1 : 1))
    .map((item) => item.font);
}

function chipsOf(state) {
  if (!state || !Array.isArray(state.styleLibrary)) {
    return DEFAULT_CHIPS.map((chip) => ({ name: chip.name }));
  }
  return state.styleLibrary;
}

function fontIdFromList(value) {
  const found = fontsOf(currentState()).find((font) => font.id == value);
  return found ? found.id : value;
}

function sampleText(region) {
  const translation = region && region.translation != null ? String(region.translation) : "";
  if (translation.trim()) return translation;
  const original = region && region.text != null ? String(region.text) : "";
  if (original.trim()) return original;
  return "Я ГОЛОДЕН!";
}

function sampleCss(style, fonts) {
  const parts = [`color:${rgbToHex(style.fill_rgb)}`];
  const font = fonts.find((item) => item.id == style.font_id);
  const family = font ? cssFamily(font.family || "") : "";
  if (family) parts.push(`font-family:${family}`);
  if (style.stroke_mode !== "none") {
    const color = style.stroke_rgb ? rgbToHex(style.stroke_rgb) : rgbToHex(contrastRgb(style.fill_rgb));
    parts.push(`-webkit-text-stroke:${widthShown(style.stroke_width)}px ${color}`);
    parts.push("paint-order:stroke fill");
  } else {
    parts.push("-webkit-text-stroke:0px transparent");
  }
  parts.push(`transform:rotate(${-Number(shownNumber(style.rotation)) || 0}deg)`);
  return parts.join(";");
}

function cssFamily(family) {
  const clean = String(family || "").replace(/[\\'"]/g, "").trim();
  if (!clean) return "";
  return `'${clean}'`;
}

function viewStyle(region) {
  const style = isPlain(region && region.style) ? region.style : {};
  const warp = isPlain(style.warp) ? style.warp : {};
  return {
    fill_rgb: Array.isArray(style.fill_rgb) ? normalizeRgb(style.fill_rgb) : [0, 0, 0],
    stroke_rgb: Array.isArray(style.stroke_rgb) ? normalizeRgb(style.stroke_rgb) : null,
    font_id: style.font_id == null ? "" : style.font_id,
    stroke_mode: style.stroke_mode === "none" || style.stroke_mode === "custom" ? style.stroke_mode : "auto",
    stroke_width: style.stroke_width == null ? 0 : style.stroke_width,
    rotation: style.rotation == null ? 0 : style.rotation,
    warp: {
      kind: warp.kind || "none",
      bend: warp.bend == null ? 0 : warp.bend,
      quad: Object.prototype.hasOwnProperty.call(warp, "quad") ? warp.quad : null,
      mesh: Object.prototype.hasOwnProperty.call(warp, "mesh") ? warp.mesh : null,
    },
  };
}

function ensureStyle(region) {
  const previous = isPlain(region.style) ? region.style : {};
  const style = {
    ...previous,
    fill_rgb: Array.isArray(previous.fill_rgb) ? normalizeRgb(previous.fill_rgb) : [0, 0, 0],
    stroke_rgb: Array.isArray(previous.stroke_rgb) ? normalizeRgb(previous.stroke_rgb) : null,
    font_id: previous.font_id == null ? "" : previous.font_id,
    stroke_mode: previous.stroke_mode || "auto",
    stroke_width: previous.stroke_width == null ? 0 : previous.stroke_width,
    rotation: previous.rotation == null ? 0 : previous.rotation,
    warp: warpFrom(previous.warp),
  };
  for (const key of KEEP_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(previous, key)) style[key] = previous[key];
  }
  region.style = style;
  return style;
}

function warpFrom(previous) {
  const source = isPlain(previous) ? { ...previous } : {};
  if (!source.kind) source.kind = "none";
  if (source.bend == null) source.bend = 0;
  if (!Object.prototype.hasOwnProperty.call(source, "quad")) source.quad = null;
  if (!Object.prototype.hasOwnProperty.call(source, "mesh")) source.mesh = null;
  return source;
}

function writeWidth(style, raw) {
  const width = widthShown(raw);
  style.stroke_width = width;
  if (width > 0 && (style.stroke_mode || "auto") === "auto") style.stroke_mode = "custom";
}

function writeRotation(style, raw) {
  const number = Number(raw);
  style.rotation = Number.isFinite(number) ? number : 0;
}

function writeBend(style, raw) {
  if (!isPlain(style.warp)) style.warp = warpFrom(null);
  style.warp.bend = bendShown(raw);
}

function applyPreset(style, preset) {
  if (!isPlain(style.warp)) style.warp = warpFrom(null);
  const warp = style.warp;
  const current = Number(warp.bend);
  const bend = Number.isFinite(current) ? current : 0;
  if (preset === "none") {
    warp.kind = "none";
    warp.bend = 0;
  } else if (preset === "arc-up") {
    warp.kind = "arc";
    warp.bend = 0.35;
  } else if (preset === "arc-down") {
    warp.kind = "arc";
    warp.bend = -0.35;
  } else if (preset === "ring") {
    warp.kind = "ring";
    warp.bend = bend === 0 ? 0.35 : bend;
  } else if (preset === "wave") {
    warp.kind = "wave";
    warp.bend = 0.35;
  } else if (preset === "flag") {
    warp.kind = "wave";
    warp.bend = 0.15;
  } else if (preset === "perspective") {
    warp.kind = "perspective";
    warp.bend = bend;
  } else if (preset === "mesh") {
    warp.kind = "mesh";
    warp.bend = bend;
  }
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
  return "";
}

function viewKey(state, region, mode) {
  const id = region ? String(region.id) : "";
  const fonts = fontsOf(state).map((font) => `${font.id}:${font.family || ""}`).join("\n");
  const chips = chipsOf(state).map((chip) => (chip && chip.name) || "").join("\n");
  return [mode, id, fontQuery, fonts, chips].join("|");
}

function shouldPatch(mode) {
  const active = document.activeElement;
  if (!panel || !active || !panel.contains(active) || !active.dataset) return false;
  const keep = active.dataset.keep;
  if (keep !== "stroke-width" && keep !== "bend" && keep !== "fill" && keep !== "stroke" && keep !== "rotation") return false;
  const visible = panel.querySelector(".style-state:not([hidden])");
  return Boolean(visible && visible.dataset.state === mode);
}

function syncLive(state, region, mode) {
  if (!region) return;
  const scope = panel.querySelector(".style-state:not([hidden])");
  if (!scope) return;
  const style = viewStyle(region);
  const fonts = fontsOf(state);
  const width = widthShown(style.stroke_width);
  const bend = bendShown(style.warp.bend);
  const widthInput = scope.querySelector("[data-keep='stroke-width']");
  const widthOut = scope.querySelector("output[for='stroke-width']");
  if (widthOut) widthOut.textContent = String(width);
  if (widthInput && document.activeElement !== widthInput) widthInput.value = String(width);
  const bendInput = scope.querySelector("[data-keep='bend']");
  const bendOut = scope.querySelector("output[for='bend']");
  if (bendOut) bendOut.textContent = bend.toFixed(2);
  if (bendInput && document.activeElement !== bendInput) bendInput.value = String(bend);
  const fill = scope.querySelector("[data-keep='fill']");
  if (fill && document.activeElement !== fill) fill.value = rgbToHex(style.fill_rgb);
  const stroke = scope.querySelector("[data-keep='stroke']");
  if (stroke && document.activeElement !== stroke) stroke.value = style.stroke_rgb ? rgbToHex(style.stroke_rgb) : "#000000";
  const angle = scope.querySelector("[data-keep='rotation']");
  if (angle && document.activeElement !== angle) angle.value = shownNumber(style.rotation);
  setChecked(scope, "[data-stroke-mode]", "data-stroke-mode", style.stroke_mode);
  setChecked(scope, "[data-warp]", "data-warp", warpChoice(style.warp));
  const chips = chipsOf(state);
  scope.querySelectorAll("[data-chip]").forEach((button) => {
    const chip = chips[Number(button.getAttribute("data-chip"))];
    button.setAttribute("aria-pressed", chip && chipMatches(style, chip) ? "true" : "false");
  });
  const sample = scope.querySelector(".style-sample");
  if (sample) {
    sample.textContent = sampleText(region);
    sample.setAttribute("style", sampleCss(style, fonts));
    sample.classList.toggle("style-sample--busy", mode === "loading");
  }
}

function setChecked(scope, selector, attr, current) {
  scope.querySelectorAll(selector).forEach((button) => {
    const on = button.getAttribute(attr) === current;
    button.setAttribute("aria-checked", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  });
}

function isFinishedNumber(raw) {
  return /^-?(?:\d+\.?\d*|\.\d+)$/.test(String(raw).trim());
}

function widthShown(value) {
  let number = Math.round(Number(value));
  if (!Number.isFinite(number)) number = 0;
  if (number < 0) number = 0;
  if (number > 20) number = 20;
  return number;
}

function bendShown(value) {
  let number = Number(value);
  if (!Number.isFinite(number)) number = 0;
  if (number < -1) number = -1;
  if (number > 1) number = 1;
  return Math.round(number * 100) / 100;
}

function shownNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : "0";
}

function normalizeRgb(value) {
  const source = Array.isArray(value) ? value : [];
  return [0, 1, 2].map((index) => {
    const number = Math.round(Number(source[index]));
    if (!Number.isFinite(number)) return 0;
    return Math.min(255, Math.max(0, number));
  });
}

function rgbToHex(rgb) {
  return `#${normalizeRgb(rgb).map((part) => part.toString(16).padStart(2, "0")).join("")}`;
}

function hexToRgb(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(hex || "").trim());
  if (!match) return [0, 0, 0];
  const value = match[1];
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)];
}

function contrastRgb(rgb) {
  const [red, green, blue] = normalizeRgb(rgb);
  const luminance = 0.299 * red + 0.587 * green + 0.114 * blue;
  return luminance >= 160 ? [0, 0, 0] : [255, 255, 255];
}

function readFavorites() {
  try {
    const raw = localStorage.getItem(FAV_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    return [];
  }
}

function writeFavorites(ids) {
  try {
    localStorage.setItem(FAV_KEY, JSON.stringify(ids));
  } catch (err) {
    /* приватный режим или переполненное хранилище */
  }
}

function captureFocus() {
  const active = document.activeElement;
  if (!panel || !active || !panel.contains(active) || !active.dataset) return null;
  const keep = active.dataset.keep;
  if (!keep) return null;
  if (keep === "search") fontQuery = active.value;
  let start = null;
  let end = null;
  try {
    start = active.selectionStart;
    end = active.selectionEnd;
  } catch (err) {
    start = null;
    end = null;
  }
  return { keep, start, end };
}

function restoreFocus(saved) {
  if (!saved || !panel) return;
  const scope = panel.querySelector(".style-state:not([hidden])") || panel;
  const next = scope.querySelector(`[data-keep="${escapeCss(saved.keep)}"]`);
  if (!next) return;
  try {
    next.focus({ preventScroll: true });
  } catch (err) {
    try {
      next.focus();
    } catch (err2) {
      return;
    }
  }
  if (typeof saved.start !== "number" || typeof next.setSelectionRange !== "function") return;
  const end = typeof saved.end === "number" ? saved.end : saved.start;
  try {
    next.setSelectionRange(saved.start, end);
  } catch (err) {
    /* color и range не держат каретку */
  }
}

function eventTarget(event) {
  if (event.target instanceof Element) return event.target;
  const parent = event.target && event.target.parentElement;
  return parent instanceof Element ? parent : null;
}

function icon(id) {
  return `<svg class="icon" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

function isPlain(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function escapeCss(value) {
  if (typeof CSS !== "undefined" && CSS && typeof CSS.escape === "function") return CSS.escape(String(value));
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
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
