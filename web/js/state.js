/* Состояние вкладки: проект, документ, стек отмены. После перезагрузки берётся с сервера. */

import { getPage, putDocument } from "./api.js";

const HISTORY_LIMIT = 50;

export const DEFAULT_SETTINGS = {
  theme: "system",
  ui_scale: 100,
  source_lang: "en",
  target_lang: "ru",
  llm_base_url: "",
  llm_model: "",
  llm_thinking: false,
  llm_timeout: 300,
  ocr_backend: "vlm",
  translator_backend: "llm",
  inpainter_backend: "lama",
  reading_order: "auto",
  translate_sfx: false,
  sfx_mode: "skip",
  remote_enabled: false,
  remote_bind: "0.0.0.0",
  remote_port: 8765,
  device: "auto",
  glossary_path: "",
  detector_conf: 0.3,
  text_stroke_ratio: 0.08,
  text_margin: 0.08,
  min_font_size: 10,
  max_font_size: 128,
  export_format: "png",
  export_jpeg_quality: 90,
  export_conflict: "rename",
  models_dir: "",
  single_key_shortcuts: true,
  first_run_complete: false,
  recent_projects: [],
};

const STAGE_LABELS = {
  detect: "Детекция",
  detection: "Детекция",
  ocr: "OCR",
  translate: "Перевод",
  translation: "Перевод",
  segment: "Маска",
  mask: "Маска",
  inpaint: "Очистка",
  clean: "Очистка",
  typeset: "Вёрстка",
};

const listeners = new Set();
const histories = new Map();
const acked = new Map();

let state = emptyState();
let coalesceKey = "";
let saveTimer = 0;
let timerPage = "";
let inflight = "";
let queuedPage = "";
let loadToken = 0;
const pendingBody = new Map();

function emptyState() {
  return {
    booted: false,
    offline: false,
    offlineMessage: "",
    version: "",
    settings: { ...DEFAULT_SETTINGS },
    settingsWarning: "",
    project: null,
    pages: [],
    recent: [],
    llm: { ok: null, models: [], vision: false },
    device: "",
    modelsReady: true,
    busy: false,
    job: { stage: "", index: 0, total: 0, pageId: "" },
    batch: { status: "idle", startedAt: null, done: 0, error: "", currentId: "" },
    fonts: [],
    styleLibrary: [],
    stylePreview: { status: "idle", message: "" },
    remote: { enabled: false, clients: 0, addresses: [], pairing_code: "", devices: [], recent: [] },
    hasApiKey: false,
    activePageId: "",
    focusPageId: "",
    selectedPageIds: [],
    anchorPageId: "",
    document: null,
    selectedRegionId: null,
    view: "original",
    showBoxes: false,
    showMask: false,
    tool: "select",
    brushSize: 12,
    zoom: "fit",
    curtain: 0.58,
    imageSize: { w: 0, h: 0 },
    banners: [],
    undoCount: 0,
    redoCount: 0,
    paths: null,
    pendingAction: null,
  };
}

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit() {
  listeners.forEach((listener) => listener(state));
}

export function patch(partial) {
  state = { ...state, ...partial };
  emit();
}

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function sameId(a, b) {
  return String(a) === String(b);
}

export function stageLabel(stage) {
  if (!stage) return "";
  const key = String(stage).toLowerCase();
  return STAGE_LABELS[key] || String(stage);
}

export function normalizeStatus(status) {
  const value = String(status || "idle").toLowerCase();
  if (value === "queue" || value === "queued") return "queued";
  if (value === "run" || value === "running" || value === "working") return "running";
  if (value === "ready" || value === "done") return "done";
  if (value === "edit" || value === "edited") return "edited";
  if (value === "no_llm" || value === "offline") return "offline";
  if (value === "failed" || value === "error") return "error";
  return "idle";
}

export function isReadyStatus(status) {
  const value = normalizeStatus(status);
  return value === "done" || value === "edited" || value === "offline";
}

export function readyCount(pages) {
  return (pages || []).filter((page) => isReadyStatus(page.status)).length;
}

export function statusText(page) {
  const status = normalizeStatus(page && page.status);
  if (status === "queued") return "в очереди";
  if (status === "running") {
    const progress = Math.max(0, Math.min(100, Math.round(Number(page.progress) || 0)));
    const stage = stageLabel(page.stage);
    return stage ? `идёт ${progress} % · ${stage}` : `идёт ${progress} %`;
  }
  if (status === "done") return "готово";
  if (status === "edited") return "есть правки";
  if (status === "offline") return "без LLM";
  if (status === "error") return "ошибка";
  return "не начата";
}

export function plural(count, one, few, many) {
  const abs = Math.abs(Number(count)) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

function normalizeRegion(raw) {
  const style = raw && raw.style && typeof raw.style === "object" ? { ...raw.style } : {};
  if (style.font_size_override == null) style.font_size_override = 0;
  if (style.uppercase == null) style.uppercase = false;
  const bbox = Array.isArray(raw.bbox) ? raw.bbox.map((item) => Number(item) || 0) : [0, 0, 0, 0];
  const type = raw.type || raw.block_type || "dialogue";
  return {
    ...raw,
    id: raw.id,
    bbox,
    text: raw.text == null ? "" : String(raw.text),
    translation: raw.translation == null ? "" : String(raw.translation),
    type,
    block_type: type,
    speaker: raw.speaker == null ? "" : String(raw.speaker),
    skip: Boolean(raw.skip),
    manual: Boolean(raw.manual),
    edited: Boolean(raw.edited),
    overflow: Boolean(raw.overflow),
    style,
  };
}

export function normalizeDocument(raw) {
  const data = raw && typeof raw === "object" ? raw : {};
  return {
    version: Number(data.version) || 0,
    regions: Array.isArray(data.regions) ? data.regions.map(normalizeRegion) : [],
    strokes: Array.isArray(data.strokes)
      ? data.strokes.map((stroke) => ({
        mode: stroke.mode === "erase" ? "erase" : "paint",
        radius: Math.max(1, Number(stroke.radius) || 1),
        points: Array.isArray(stroke.points)
          ? stroke.points.map((point) => [Number(point[0]) || 0, Number(point[1]) || 0])
          : [],
      }))
      : [],
    reading_direction: data.reading_direction || "ltr",
    warnings: Array.isArray(data.warnings) ? data.warnings.map(String) : [],
    timings: data.timings && typeof data.timings === "object" ? { ...data.timings } : {},
    ocr_engine: data.ocr_engine || "",
    translator_engine: data.translator_engine || "",
  };
}

export function normalizePage(raw, index) {
  const source = raw || {};
  return {
    id: String(source.id ?? ""),
    name: source.name || source.filename || source.file || "page",
    status: normalizeStatus(source.status),
    progress: Number(source.progress) || 0,
    stage: source.stage || source.step || "",
    error: source.error || "",
    chapter: source.chapter == null ? "" : String(source.chapter),
    overflow: Boolean(source.overflow),
    version: Number(source.version ?? source.document_version ?? source.document?.version ?? 0) || 0,
    index,
  };
}

function normalizePages(list) {
  return (Array.isArray(list) ? list : []).map((item, index) => normalizePage(item, index)).filter((item) => item.id);
}

function normalizeLlm(raw) {
  if (!raw || typeof raw !== "object") return { ok: null, models: [], vision: false, reason: "" };
  let ok = null;
  if (raw.ok === true || raw.ok === false) ok = raw.ok;
  else if (typeof raw.available === "boolean") ok = raw.available;
  return {
    ok,
    models: Array.isArray(raw.models) ? raw.models : [],
    vision: Boolean(raw.vision),
    reason: raw.reason || "",
  };
}

function readWarning(data) {
  const raw = data.settings_warning ?? data.settingsWarning ?? "";
  if (Array.isArray(raw)) return raw.filter(Boolean).join(" ");
  if (typeof raw === "string") return raw;
  if (raw && typeof raw === "object") return raw.message || "";
  return "";
}

function readDevice(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") return value.name || value.kind || value.device || "";
  return String(value);
}

function normalizeRecent(data, settings) {
  const raw = data.recent || data.recent_projects || settings.recent_projects || [];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (typeof item === "string") return { id: item, name: item, path: "" };
    return {
      id: String(item.id || ""),
      name: item.name || item.title || item.id || "",
      path: item.path || item.folder || "",
      when: item.when || item.opened || item.opened_at || "",
    };
  }).filter((item) => item.id);
}

function historyOf(pageId) {
  if (!histories.has(pageId)) histories.set(pageId, { past: [], future: [] });
  return histories.get(pageId);
}

function syncHistoryFlags() {
  const history = state.activePageId ? historyOf(state.activePageId) : { past: [], future: [] };
  state = { ...state, undoCount: history.past.length, redoCount: history.future.length };
}

export function settingsForSave(settings) {
  const copy = { ...settings };
  delete copy.api_key;
  delete copy.has_api_key;
  return copy;
}

export function applyBootstrap(data) {
  const incoming = data && typeof data === "object" ? data : {};
  const settings = { ...DEFAULT_SETTINGS, ...(incoming.settings || {}) };
  const pages = normalizePages(incoming.pages || incoming.project?.pages || []);
  const project = incoming.project || null;
  let active = state.activePageId;
  if (!active || !pages.some((page) => page.id === active)) active = pages[0] ? pages[0].id : "";
  state = {
    ...state,
    booted: true,
    offline: false,
    offlineMessage: "",
    version: incoming.version || state.version || "",
    settings,
    settingsWarning: readWarning(incoming),
    project,
    pages,
    recent: normalizeRecent(incoming, settings),
    llm: normalizeLlm(incoming.llm),
    device: readDevice(incoming.device),
    modelsReady: incoming.models_ready !== false,
    busy: Boolean(incoming.busy),
    activePageId: project ? active : "",
    focusPageId: project ? active : "",
    selectedPageIds: project && active ? [active] : [],
    anchorPageId: project ? active : "",
    paths: incoming.paths || null,
    hasApiKey: Boolean(incoming.has_api_key || incoming.settings?.has_api_key || incoming.llm?.has_api_key),
  };
  syncHistoryFlags();
  emit();
  if (state.activePageId) reloadDetail(state.activePageId);
}

export function setProject(project, pages) {
  const list = normalizePages(pages || project?.pages || []);
  const active = list[0] ? list[0].id : "";
  state = {
    ...state,
    project: project || null,
    pages: list,
    activePageId: active,
    focusPageId: active,
    selectedPageIds: active ? [active] : [],
    anchorPageId: active,
    document: null,
    selectedRegionId: null,
    imageSize: { w: 0, h: 0 },
  };
  syncHistoryFlags();
  emit();
  if (active) reloadDetail(active);
}

export function updatePage(pageId, partial) {
  const pages = state.pages.map((page) => (page.id === String(pageId) ? { ...page, ...partial } : page));
  patch({ pages });
}

export function selectPages(ids, activeId, focusId) {
  const selected = ids.map(String);
  const active = activeId ? String(activeId) : (selected[0] || "");
  const focus = focusId ? String(focusId) : active;
  const changed = active !== state.activePageId;
  if (changed && timerPage && timerPage !== active) {
    const leaving = timerPage;
    window.clearTimeout(saveTimer);
    timerPage = "";
    flush(leaving);
  }
  state = {
    ...state,
    selectedPageIds: selected,
    activePageId: active,
    focusPageId: focus,
    anchorPageId: state.anchorPageId,
    selectedRegionId: changed ? null : state.selectedRegionId,
    document: changed ? null : state.document,
    imageSize: changed ? { w: 0, h: 0 } : state.imageSize,
  };
  syncHistoryFlags();
  emit();
  if (changed && active) reloadDetail(active);
}

export function setAnchor(pageId) {
  state = { ...state, anchorPageId: String(pageId || "") };
}

export function moveFocus(pageId) {
  patch({ focusPageId: String(pageId || "") });
}

export function reloadDetail(pageId) {
  const token = ++loadToken;
  const id = String(pageId);
  getPage(id).then((data) => {
    if (token !== loadToken || state.activePageId !== id) return;
    applyDetail(id, data, false);
  }).catch((error) => {
    if (token !== loadToken) return;
    setBanner("save", {
      tone: "warning",
      text: error.message || "Не удалось открыть страницу",
    });
  });
}

function unwrapDetail(data) {
  const root = data || {};
  const page = root.page || root;
  const document = root.document || page.document || null;
  return { page, document };
}

export function applyDetail(pageId, data, keepLocal, force = false) {
  const id = String(pageId);
  const unwrapped = unwrapDetail(data);
  if (unwrapped.page && unwrapped.page.id) {
    const normalized = normalizePage(unwrapped.page, state.pages.findIndex((item) => item.id === id));
    state = {
      ...state,
      pages: state.pages.map((item) => (item.id === id ? { ...item, ...normalized, id } : item)),
    };
  }
  if (!unwrapped.document) {
    emit();
    return;
  }
  const document = normalizeDocument(unwrapped.document);
  acked.set(id, document.version);
  const overflow = document.regions.some((region) => region.overflow);
  state = {
    ...state,
    pages: state.pages.map((item) => (item.id === id ? { ...item, overflow } : item)),
  };
    const dirty = isDirty(id) && state.activePageId === id && state.document;
    if ((keepLocal || dirty) && !force) {
      if (state.document) state = { ...state, document: { ...state.document, version: document.version } };
      emit();
      return;
    }
  if (state.activePageId === id) {
    state = { ...state, document };
    syncHistoryFlags();
  }
  emit();
}

export function isDirty(pageId) {
  const id = String(pageId || "");
  return inflight === id || timerPage === id || queuedPage === id || pendingBody.has(id);
}

function contentKey(document) {
  if (!document) return "";
  const copy = clone(document);
  delete copy.version;
  return JSON.stringify(copy);
}

export function editDocument(mutator, options = {}) {
  if (!state.activePageId || !state.document) return;
  const pageId = state.activePageId;
  const before = contentKey(state.document);
  const next = clone(state.document);
  mutator(next);
  if (contentKey(next) === before) return;
  const key = options.coalesce || "";
  const history = historyOf(pageId);
  if (!key || key !== coalesceKey) {
    history.past.push(clone(state.document));
    if (history.past.length > HISTORY_LIMIT) history.past.shift();
    history.future = [];
    coalesceKey = key;
  }
  if (!key) coalesceKey = "";
  state = { ...state, document: next };
  pendingBody.set(pageId, clone(next));
  syncHistoryFlags();
  emit();
  scheduleSave(pageId, options.debounce || 0);
}

export function undo() {
  if (!state.activePageId || !state.document) return;
  const history = historyOf(state.activePageId);
  if (!history.past.length) return;
  history.future.push(clone(state.document));
  if (history.future.length > HISTORY_LIMIT) history.future.shift();
  const previous = history.past.pop();
  coalesceKey = "";
  state = { ...state, document: previous };
  syncHistoryFlags();
  emit();
  scheduleSave(state.activePageId, 0);
}

export function redo() {
  if (!state.activePageId || !state.document) return;
  const history = historyOf(state.activePageId);
  if (!history.future.length) return;
  history.past.push(clone(state.document));
  if (history.past.length > HISTORY_LIMIT) history.past.shift();
  const next = history.future.pop();
  coalesceKey = "";
  state = { ...state, document: next };
  syncHistoryFlags();
  emit();
  scheduleSave(state.activePageId, 0);
}

export function clearHistory(pageId) {
  histories.set(String(pageId), { past: [], future: [] });
  coalesceKey = "";
  if (state.activePageId === String(pageId)) syncHistoryFlags();
  emit();
}

export function whenSaved(pageId) {
  const id = String(pageId || state.activePageId || "");
  if (timerPage === id) {
    window.clearTimeout(saveTimer);
    saveTimer = 0;
    timerPage = "";
    flush(id);
  }
  if (!id || !isDirty(id)) return Promise.resolve();
  return new Promise((resolve) => {
    const check = () => {
      if (!isDirty(id)) resolve();
      else window.setTimeout(check, 20);
    };
    check();
  });
}

function scheduleSave(pageId, delay) {
  if (state.activePageId === pageId && state.document) pendingBody.set(pageId, clone(state.document));
  timerPage = pageId;
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    if (timerPage === pageId) timerPage = "";
    flush(pageId);
  }, delay);
}

async function flush(pageId) {
  if (!pendingBody.has(pageId)) return;
  if (inflight) {
    queuedPage = pageId;
    return;
  }
  const body = pendingBody.get(pageId);
  pendingBody.delete(pageId);
  inflight = pageId;
  if (queuedPage === pageId) queuedPage = "";
  const base = acked.has(pageId) ? acked.get(pageId) : Number(body.version) || 0;
  body.version = base;
  try {
    let response;
    try {
      response = await putDocument(pageId, base, body);
    } catch (error) {
      if (error.status !== 409) throw error;
      const serverVersion = await conflictVersion(pageId, error);
      if (serverVersion == null) throw error;
      acked.set(pageId, serverVersion);
      const latest = pendingBody.get(pageId) || body;
      pendingBody.delete(pageId);
      latest.version = serverVersion;
      response = await putDocument(pageId, serverVersion, latest);
    }
    acceptSave(pageId, response, base);
  } catch (error) {
    coalesceKey = "";
    pendingBody.delete(pageId);
    queuedPage = "";
    if (error.status === 409) {
      setBanner("conflict", {
        tone: "warning",
        text: "Страница изменилась, правка не сохранена",
      });
      if (state.activePageId === pageId) {
        const token = ++loadToken;
        try {
          const fresh = await getPage(pageId);
          if (token === loadToken && state.activePageId === pageId) {
            clearHistory(pageId);
            applyDetail(pageId, fresh, false, true);
          }
        } catch (loadError) {
          setBanner("save", { tone: "warning", text: loadError.message || "Не удалось перечитать страницу" });
        }
      }
    } else {
      setBanner("save", { tone: "warning", text: error.message || "Не удалось сохранить правку" });
    }
  } finally {
    const next = queuedPage;
    inflight = "";
    queuedPage = "";
    if (next) flush(next);
    else emit();
  }
}

function acceptSave(pageId, response, fallback) {
  const version = readVersion(response, fallback);
  acked.set(pageId, version);
  if (state.activePageId === pageId && state.document && !pendingBody.has(pageId)) {
    if (response && response.document) {
      const normalized = normalizeDocument(response.document);
      normalized.version = version;
      state = { ...state, document: normalized };
    } else {
      state = { ...state, document: { ...state.document, version } };
    }
  }
  state = {
    ...state,
    pages: state.pages.map((page) => (page.id === pageId ? { ...page, version } : page)),
  };
  if (state.activePageId === pageId) coalesceKey = "";
}

async function conflictVersion(pageId, error) {
  const fromBody = readVersion(error && error.body, null);
  if (fromBody != null) return fromBody;
  try {
    const fresh = await getPage(pageId);
    return readVersion(fresh, null);
  } catch (loadError) {
    return null;
  }
}

function readVersion(response, fallback) {
  if (!response) return fallback;
  if (response.document && response.document.version != null) return Number(response.document.version);
  if (response.version != null && !response.regions) return Number(response.version);
  if (response.version != null) return Number(response.version);
  if (response.page && response.page.version != null) return Number(response.page.version);
  return fallback;
}

export function setBanner(id, banner) {
  const banners = state.banners.filter((item) => item.id !== id);
  if (banner) banners.push({ id, tone: banner.tone || "warning", text: banner.text, actions: banner.actions || [] });
  patch({ banners });
}

export function dismissBanner(id) {
  setBanner(id, null);
}

export function selectRegion(regionId) {
  patch({ selectedRegionId: regionId == null ? null : regionId });
}

export function findRegion(document, regionId) {
  if (!document) return null;
  return document.regions.find((region) => sameId(region.id, regionId)) || null;
}

export function nextRegionId(document) {
  const ids = (document?.regions || []).map((region) => Number(region.id)).filter((id) => Number.isFinite(id));
  return (ids.length ? Math.max(...ids) : 0) + 1;
}

export function clampBox(box, width, height) {
  let [x, y, boxW, boxH] = box.map((value) => Math.round(Number(value) || 0));
  boxW = Math.max(4, boxW);
  boxH = Math.max(4, boxH);
  if (width > 0) {
    boxW = Math.min(boxW, width);
    x = Math.min(Math.max(0, x), Math.max(0, width - boxW));
  } else {
    x = Math.max(0, x);
  }
  if (height > 0) {
    boxH = Math.min(boxH, height);
    y = Math.min(Math.max(0, y), Math.max(0, height - boxH));
  } else {
    y = Math.max(0, y);
  }
  return [x, y, boxW, boxH];
}

export function blankRegion(id, bbox) {
  return {
    id,
    bbox,
    class_name: "text_free",
    confidence: 1,
    text: "",
    translation: "",
    type: "dialogue",
    block_type: "dialogue",
    speaker: "",
    speaker_gender: "",
    bubble_bbox: null,
    order: 0,
    skip: false,
    manual: true,
    edited: true,
    overflow: false,
    style: {
      fill_rgb: [0, 0, 0],
      stroke_rgb: null,
      font_size: 16,
      alignment: "center",
      uppercase: false,
      line_height: 18,
      font_size_override: 0,
    },
  };
}

export function liveText(current) {
  if (current.offline) return "Нет связи с программой";
  if (current.busy) {
    const stage = stageLabel(current.job.stage) || "Обработка";
    const total = current.job.total || current.pages.length;
    const index = current.job.index || pageNumber(current, current.job.pageId || current.activePageId);
    if (total) return `${stage} · страница ${index} из ${total}`;
    return stage;
  }
  if (!current.project) return "Нет открытого проекта";
  return `${readyCount(current.pages)} из ${current.pages.length} готово`;
}

export function visualStatus(current) {
  if (current.offline) return "Нет связи с программой";
  if (current.busy) return liveText(current);
  if (!current.project) return "Нет открытого проекта";
  const page = current.pages.find((item) => item.id === current.activePageId);
  if (!page) return `${readyCount(current.pages)} из ${current.pages.length} готово`;
  const status = normalizeStatus(page.status);
  if (status === "running") return liveText({ ...current, busy: true });
  return `${statusText(page)} · страница ${pageNumber(current, page.id)}`;
}

export function pageNumber(current, pageId) {
  const index = current.pages.findIndex((page) => page.id === String(pageId));
  return index >= 0 ? index + 1 : 1;
}

export function deviceLabel(value) {
  const text = String(value || "").trim();
  const low = text.toLowerCase();
  if (!low) return "—";
  if (low.includes("cpu")) return "CPU";
  if (low.includes("gpu") || low.includes("cuda") || low.includes("directml")) return "GPU";
  return text;
}
