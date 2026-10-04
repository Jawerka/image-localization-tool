/* Сборка окна: сессия, события, тулбар, баннеры и команды. */

import {
  bootstrap,
  cancelJobs,
  connectEvents,
  dialogFiles,
  dialogFolder,
  dialogLog,
  dialogReveal,
  dropPaths,
  imageUrl,
  importSources,
  jobs,
  llmCheck,
  openRecent,
  pauseJobs,
  pickFolder,
  putSettings,
  remoteStatus,
  removePages,
  resumeJobs,
  retryErrors,
  session,
  translate,
} from "./api.js";
import { render as renderBatch } from "./batch-panel.js";
import { closeTop, confirm, init as initDialogs, isAnyOpen, openExport, openGlossary, openHotkeys, openWorker } from "./dialogs.js";
import { init as initInspector } from "./inspector.js";
import { install as installKeys } from "./keys.js";
import { closeMenu, init as initPages, menuOpen } from "./pages.js";
import {
  applyAppearance,
  init as initSettings,
  isOpen as settingsOpen,
  isPreviewing,
  isWizard,
  noteModelProgress,
  open as openSettings,
  openWizard,
} from "./settings.js";
import {
  applyBootstrap,
  clampBox,
  deviceLabel,
  editDocument,
  findRegion,
  getState,
  isDirty,
  liveText,
  pageNumber,
  patch,
  redo,
  reloadDetail,
  selectPages,
  selectRegion,
  setAnchor,
  setBanner,
  setProject,
  settingsForSave,
  subscribe,
  undo,
  updatePage,
  visualStatus,
} from "./state.js";
import { init as initViewer, nudgeBrush, setSpace, setZoom } from "./viewer.js";

let bannerMarkup = "";
let recentMarkup = "";
let appearanceKey = "";
let copiedStyle = null;
let remoteTimer = 0;

const DROP_HINT = "Перетащите файлы в окно приложения или воспользуйте кнопки Открыть";

function icon(id) {
  return `<svg class="icon" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

function start() {
  initPages(onPageCommand);
  initViewer();
  initInspector();
  initSettings();
  initDialogs();
  installKeys({
    hotkeys: () => openHotkeys(),
    escape,
    modal: () => isAnyOpen() || isWizard(),
    settingsOpen,
    space: setSpace,
    openFiles,
    openFolder,
    export: () => openExport(),
    settings: () => openSettings(),
    translatePage,
    translateAll,
    undo,
    redo,
    copyStyle: copyRegionStyle,
    pasteStyle: pasteRegionStyle,
    nextProblem: focusNextProblem,
    zoomFit: () => setZoom("fit"),
    zoom100: () => setZoom(1),
    page: movePage,
    nudge,
    deleteRegion,
    brush: nudgeBrush,
    tool: (tool) => patch({ tool }),
    view: (view) => patch({ view }),
    mask: () => patch({ showMask: !getState().showMask }),
    boxes: () => patch({ showBoxes: !getState().showBoxes }),
  });
  bindChrome();
  subscribe(render);
  window.addEventListener("beforeunload", (event) => {
    if (!getState().busy) return;
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("contextmenu", (event) => {
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    event.preventDefault();
  });
  document.addEventListener("ilt-undo", () => undo());
  document.addEventListener("ilt-page", (event) => movePage(Number(event.detail) || 0));
  document.addEventListener("ilt-redo", () => redo());
  document.addEventListener("ilt-translate-page", () => translatePage());
  document.addEventListener("ilt-banner", (event) => {
    if (event.detail) setBanner(event.detail.id || "notice", { text: event.detail.text });
  });
  boot();
}

function bindChrome() {
  document.querySelectorAll("[data-role='open-files']").forEach((button) => button.addEventListener("click", openFiles));
  document.querySelectorAll("[data-role='open-folder']").forEach((button) => button.addEventListener("click", openFolder));
  document.querySelectorAll("[data-role='export']").forEach((button) => button.addEventListener("click", () => {
    closeMenus();
    openExport();
  }));
  document.querySelectorAll("[data-role='settings']").forEach((button) => button.addEventListener("click", () => {
    closeMenus();
    openSettings();
  }));
  document.querySelector("[data-role='exit']").addEventListener("click", () => {
    closeMenus();
    exitApp();
  });
  document.querySelector("[data-role='hotkeys-menu']").addEventListener("click", () => {
    closeMenus();
    openHotkeys();
  });
  document.querySelector("[data-role='translate-page']").addEventListener("click", translatePage);
  document.querySelector("[data-role='translate-all']").addEventListener("click", translateAll);
  document.querySelector("[data-role='stop']").addEventListener("click", () => stopJobs());
  document.querySelectorAll("[data-role='llm-retry']").forEach((button) => button.addEventListener("click", retryLlm));
  document.querySelector("[data-role='lang-target']").addEventListener("change", saveLanguages);
  document.querySelectorAll("input[name='sfx-mode']").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) saveSfxMode(input.value);
    });
  });
  document.querySelector("[data-role='glossary']")?.addEventListener("click", () => {
    closeMenus();
    openGlossary();
  });
  document.querySelector("[data-role='banners']").addEventListener("click", onBannerClick);
  document.querySelector("[data-role='recent-list']").addEventListener("click", onRecent);
  document.querySelector("[data-role='error-log']").addEventListener("click", () => {
    dialogLog().catch((error) => {
      document.querySelector("[data-role='error-text']").textContent = error.message || "Не удалось открыть лог";
    });
  });
  window.addEventListener("dragenter", onDrag);
  window.addEventListener("dragover", onDrag);
  window.addEventListener("dragleave", () => document.querySelector("[data-role='empty-drop']")?.classList.remove("is-dragover"));
  window.addEventListener("drop", onDrop);
}

async function boot() {
  try {
    await takeToken();
    const data = await bootstrap();
    applyBootstrap(data);
    const settings = getState().settings;
    applyAppearance(settings.theme, settings.ui_scale);
    connectEvents(onEvent);
    window.setInterval(renderRunClock, 1000);
    syncJobs();
    refreshRemote();
    remoteTimer = window.setInterval(refreshRemote, 5000);
    if (settings.first_run_complete === false) openWizard();
  } catch (error) {
    showOffline(error.message || "Нет связи с программой");
  }
}

async function takeToken() {
  const params = new URLSearchParams(location.search);
  const token = params.get("k");
  if (!token) return;
  await session(token);
  params.delete("k");
  const query = params.toString();
  history.replaceState(null, "", `${location.pathname}${query ? `?${query}` : ""}${location.hash}`);
}

function showOffline(message) {
  patch({ offline: true, offlineMessage: message });
  document.querySelector("[data-role='shell']").hidden = true;
  const screen = document.querySelector("[data-role='screen-error']");
  screen.hidden = false;
  document.querySelector("[data-role='error-text']").textContent = message;
}

function render(state) {
  if (state.offline) return;
  if (!isPreviewing()) {
    const appearance = `${state.settings.theme}:${state.settings.ui_scale}`;
    if (appearance !== appearanceKey) {
      appearanceKey = appearance;
      applyAppearance(state.settings.theme, state.settings.ui_scale);
    }
  }
  const target = document.querySelector("[data-role='lang-target']");
  if (document.activeElement !== target && target.value !== state.settings.target_lang) target.value = state.settings.target_lang || "ru";
  const hasPages = state.pages.length > 0;
  const hasPage = Boolean(state.activePageId);
  document.querySelector("[data-role='translate-page']").disabled = !hasPage;
  document.querySelector("[data-role='translate-all']").disabled = !hasPages;
  document.querySelectorAll("[data-role='export']").forEach((button) => {
    button.disabled = !hasPages;
  });
  const batchLive = state.batch && (state.batch.status === "running" || state.batch.status === "paused");
  document.querySelector("[data-role='stop']").hidden = !state.busy && !batchLive;
  document.querySelector("[data-role='empty']").hidden = hasPages;
  syncSfx(state.settings);
  const clients = Number(state.remote && state.remote.clients) || 0;
  const net = document.querySelector("[data-role='net-clients']");
  if (net) net.textContent = `Сеть: ${clients} клиентов`;
  const batchFold = document.querySelector("[data-role='batch-fold']");
  if (batchFold) {
    batchFold.hidden = !hasPages;
    if (hasPages) renderBatch(document.querySelector("[data-role='batch-root']"), batchState(state), batchActions);
  }
  renderBanners(state);
  renderRecent(state);
  renderStatus(state);
}

function renderBanners(state) {
  const host = document.querySelector("[data-role='banners']");
  if (!state.booted) {
    host.innerHTML = "";
    return;
  }
  const items = [];
  if (state.settingsWarning) items.push({ id: "settings-warning", text: state.settingsWarning, actions: [] });
  if (state.modelsReady === false) {
    items.push({ id: "models", text: "Нет моделей.", actions: [{ id: "models", label: "Установить" }] });
  }
  if (state.llm?.ok === false) {
    items.push({
      id: "llm",
      text: "LLM недоступен. Страницы пойдут через RapidOCR и Argos.",
      actions: [{ id: "settings", label: "Настройки", tab: "llm" }, { id: "llm", label: "Повторить" }],
    });
  }
  state.banners.forEach((banner) => {
    if (!items.some((item) => item.id === banner.id)) items.push(banner);
  });
  const markup = items.map((banner) => `<div class="banner banner--warning" data-role="banner" role="status">
    <svg class="icon banner__icon" aria-hidden="true"><use href="icons/icons.svg#warning"></use></svg>
    <p class="banner__text">${escapeText(banner.text)}</p>
    <div class="banner__actions">${(banner.actions || []).map((action) => `<button type="button" class="btn ${action.id === "settings" || action.id === "models" ? "btn-accent" : "btn-ghost"}" data-banner-action="${escapeText(action.id)}" data-tab="${escapeText(action.tab || "")}">${escapeText(action.label)}</button>`).join("")}</div>
  </div>`).join("");
  if (markup === bannerMarkup) return;
  bannerMarkup = markup;
  host.innerHTML = markup;
}

function renderRecent(state) {
  const section = document.querySelector("[data-role='recent']");
  const list = document.querySelector("[data-role='recent-list']");
  const items = state.pages.length ? [] : (state.recent || []);
  const markup = items.map((item) => `<li><button type="button" class="recent__item" data-recent="${escapeText(item.id)}">
    ${icon("folder")}
    <span>${escapeText(item.name)}${item.path ? `<br><span class="muted">${escapeText(item.path)}</span>` : ""}</span>
    ${item.when ? `<small>${escapeText(item.when)}</small>` : ""}
  </button></li>`).join("");
  if (markup === recentMarkup && section.hidden === (items.length === 0)) return;
  recentMarkup = markup;
  section.hidden = items.length === 0;
  list.innerHTML = markup;
}

function renderStatus(state) {
  const job = document.querySelector("[data-role='job']");
  const live = document.querySelector("[data-role='live']");
  const visual = visualStatus(state);
  const spoken = liveText(state);
  if (job.textContent !== visual) job.textContent = visual;
  if (live.textContent !== spoken) live.textContent = spoken;
  renderImageSize(state);
  renderRunClock();
  const llm = document.querySelector("[data-role='llm']");
  const on = Boolean(state.llm?.ok);
  llm.querySelector("[data-role='llm-bullet']").className = on ? "bullet bullet--on" : "bullet bullet--off";
  llm.querySelector("[data-role='llm-text']").textContent = on ? "LLM" : "LLM нет";
  llm.querySelector("[data-role='llm-mark']").innerHTML = icon(on ? "check" : "warning");
  document.querySelector("[data-role='device-label']").textContent = deviceLabel(state.device);
}

function renderImageSize(state) {
  const node = document.querySelector("[data-role='image-size']");
  if (!node) return;
  const width = Number(state.imageSize && state.imageSize.w) || 0;
  const height = Number(state.imageSize && state.imageSize.h) || 0;
  if (!width || !height) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  const text = `${width}×${height}`;
  node.hidden = false;
  if (node.textContent !== text) node.textContent = text;
}

function ensureRunStart() {
  const batch = getState().batch || {};
  if ((batch.status === "running" || batch.status === "paused") && batch.startedAt) return batch;
  return {
    status: "running",
    startedAt: Date.now(),
    pausedAt: null,
    done: settledCount(getState().pages),
    error: "",
    currentId: "",
  };
}

function formatRun(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`;
  return `${minutes}:${seconds}`;
}

function renderRunClock() {
  const node = document.querySelector("[data-role='run-time']");
  if (!node) return;
  const batch = getState().batch || {};
  const live = batch.status === "running" || batch.status === "paused";
  if (!live || !batch.startedAt) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  const end = batch.status === "paused" && batch.pausedAt ? batch.pausedAt : Date.now();
  const text = formatRun(end - batch.startedAt);
  node.hidden = false;
  if (node.textContent !== text) node.textContent = text;
}

function onBannerClick(event) {
  const button = event.target.closest("[data-banner-action]");
  if (!button) return;
  const action = button.dataset.bannerAction;
  if (action === "settings") openSettings(button.dataset.tab || "appearance");
  if (action === "llm") retryLlm();
  if (action === "models") openSettings("models");
  if (action === "reveal") dialogReveal({}).catch(showError);
}

async function onRecent(event) {
  const button = event.target.closest("[data-recent]");
  if (!button) return;
  try {
    const data = await openRecent(button.dataset.recent);
    if (data && (data.project || data.pages)) setProject(data.project, data.pages);
  } catch (error) {
    showError(error);
  }
}

async function openFiles() {
  closeMenus();
  try {
    const data = await dialogFiles();
    takeProject(data);
  } catch (error) {
    showError(error);
  }
}

async function openFolder() {
  closeMenus();
  try {
    const data = await dialogFolder();
    takeProject(data);
  } catch (error) {
    showError(error);
  }
}

function takeProject(data) {
  if (!data || data.cancelled || data.canceled) return;
  if (data.project || data.pages) setProject(data.project, data.pages || data.project?.pages);
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  if (warnings.length) setBanner("import", { text: warnings.join(" ") });
}

async function saveLanguages() {
  const target = document.querySelector("[data-role='lang-target']").value;
  const body = settingsForSave({ ...getState().settings, source_lang: "auto", target_lang: target });
  try {
    const saved = await putSettings(body);
    const settings = saved && saved.settings ? { ...body, ...saved.settings } : (saved && saved.theme ? { ...body, ...saved } : body);
    patch({ settings });
  } catch (error) {
    showError(error);
  }
}

async function translatePage() {
  const pageId = getState().activePageId;
  if (!pageId) return;
  try {
    await translate("page", pageId);
    patch({ busy: true, batch: ensureRunStart() });
  } catch (error) {
    showError(error);
  }
}

async function translateAll() {
  if (!getState().pages.length) return;
  const batch = getState().batch || {};
  const fresh = batch.status !== "running" && batch.status !== "paused";
  try {
    await translate("all", "", { skip_ready: true });
    patch({
      busy: true,
      batch: {
        status: "running",
        startedAt: fresh ? Date.now() : (batch.startedAt || Date.now()),
        done: settledCount(getState().pages),
        error: "",
        currentId: "",
      },
    });
  } catch (error) {
    showError(error);
  }
}

async function retryLlm() {
  try {
    const result = await llmCheck();
    patch({
      llm: {
        ok: Boolean(result?.ok),
        models: result?.models || [],
        vision: Boolean(result?.vision),
        reason: result?.reason || "",
      },
    });
  } catch (error) {
    patch({ llm: { ok: false, models: [], vision: false, reason: error.message || "" } });
  }
}

async function exitApp() {
  if (getState().busy) {
    const index = getState().job.index || pageNumber(getState(), getState().activePageId);
    const total = getState().job.total || getState().pages.length;
    const ok = await confirm({
      title: "Закрыть программу?",
      text: `Идёт перевод главы (страница ${index} из ${total}). Если закрыть окно, обработка остановится и очередь очистится.`,
      ok: "Остановить и закрыть",
      cancel: "Отмена",
    });
    if (!ok) return;
    try {
      await cancelJobs();
    } catch (error) {
      showError(error);
    }
  }
  const bridge = window.pywebview && window.pywebview.api;
  if (bridge && typeof bridge.quit === "function") bridge.quit();
  else if (bridge && typeof bridge.destroy === "function") bridge.destroy();
  else window.close();
}

async function onPageCommand(action, ids, pageId) {
  try {
    if (action === "translate" || action === "retranslate") {
      await translate("page", pageId);
      patch({ busy: true, batch: ensureRunStart() });
      return;
    }
    if (action === "reveal") {
      await dialogReveal({ page_id: pageId });
      return;
    }
    if (action === "remove") {
      const ok = await confirm({
        title: ids.length > 1 ? "Убрать страницы из проекта?" : "Убрать страницу из проекта?",
        text: "Страницы будут убраны из проекта. Файлы оригиналов на диске останутся. Это нельзя отменить.",
        ok: "Убрать",
        cancel: "Отмена",
      });
      if (!ok) return;
      const data = await removePages(ids);
      if (data && (data.project || data.pages)) setProject(data.project || getState().project, data.pages || data.project?.pages);
      else setProject(getState().project, getState().pages.filter((page) => !ids.includes(page.id)));
    }
  } catch (error) {
    showError(error);
  }
}

function onEvent(type, payload) {
  if (type === "job.started" || type === "worker.restarting") {
    patch({ busy: true, batch: ensureRunStart() });
    if (type === "worker.restarting") setBanner("restart", { text: "Обработка перезапускается" });
  }
  if (type === "job.progress") onProgress(payload);
  if (type === "page.updated") onPageUpdated(payload);
  if (type === "job.finished") onFinished(payload);
  if (type === "job.failed") onFailed(payload);
  if (type === "job.cancelled") onCancelled();
  if (type === "llm.status") {
    patch({
      llm: {
        ok: payload.ok === true || payload.ok === false ? payload.ok : Boolean(payload.available),
        models: payload.models || [],
        vision: Boolean(payload.vision),
        reason: payload.reason || "",
      },
    });
  }
  if (type === "worker.failed") openWorker(payload.message || payload.error || payload.reason || "");
  if (type === "model.progress") noteModelProgress(payload);
}

function onProgress(payload) {
  setBanner("restart", null);
  const pageId = String(payload.page_id || payload.pageId || "");
  const stage = payload.stage || "";
  const progress = Number(payload.progress ?? payload.percent ?? 0);
  if (pageId) updatePage(pageId, { status: "running", progress, stage, error: "" });
  const state = getState();
  const batch = state.batch || {};
  const live = batch.status === "running" || batch.status === "paused";
  patch({
    busy: true,
    batch: live ? {
      ...batch,
      status: batch.status === "paused" ? "paused" : "running",
      currentId: pageId || batch.currentId || "",
      done: settledCount(getState().pages),
      startedAt: batch.startedAt || Date.now(),
    } : batch,
    job: {
      stage,
      pageId,
      index: Number(payload.index || payload.page_index || pageNumber(state, pageId || state.activePageId)),
      total: Number(payload.total || payload.page_count || state.pages.length),
    },
  });
}

function onPageUpdated(payload) {
  const page = payload.page || payload;
  const pageId = String(payload.page_id || payload.pageId || page.id || "");
  if (!pageId) return;
  const partial = {};
  if (page.status) partial.status = page.status;
  if (page.progress != null) partial.progress = page.progress;
  if (Object.prototype.hasOwnProperty.call(page, "stage")) partial.stage = page.stage || "";
  if (page.error != null) partial.error = page.error;
  if (page.version != null) partial.version = page.version;
  if (Object.keys(partial).length) updatePage(pageId, partial);
  const pending = getState().pendingAction;
  if (pending && String(pending.pageId) === pageId) patch({ pendingAction: null });
  if (pageId === getState().activePageId && !isDirty(pageId)) reloadDetail(pageId);
}

function onFinished(payload) {
  const batch = getState().batch || {};
  const running = batch.status === "running" || batch.status === "paused";
  const failed = getState().pages.some((page) => page.status === "error");
  const nextStatus = running ? (failed ? "error" : "finished") : batch.status;
  if (running && nextStatus === "finished") notifyBatchFinished();
  patch({
    busy: false,
    pendingAction: null,
    job: { stage: "", index: 0, total: 0, pageId: "" },
    batch: running ? {
      ...batch,
      status: nextStatus,
      done: settledCount(getState().pages),
      error: failed ? (batch.error || "Есть страницы с ошибкой") : "",
      currentId: "",
    } : batch,
  });
  setBanner("restart", null);
  const count = payload.saved ?? payload.count ?? (Array.isArray(payload.paths) ? payload.paths.length : null);
  if (payload.kind === "export" || (count != null && payload.export)) {
    const saved = Number(count) || 0;
    setBanner("export", {
      text: `Сохранено ${saved} ${savedWord(saved)}`,
      actions: [{ id: "reveal", label: "Открыть папку" }],
    });
  }
  const pageId = String(payload.page_id || getState().activePageId || "");
  if (pageId && !isDirty(pageId)) reloadDetail(pageId);
}

function onFailed(payload) {
  const batch = getState().batch || {};
  const message = payload.error || payload.message || "Обработка остановилась с ошибкой";
  const live = batch.status === "running" || batch.status === "paused";
  patch({
    busy: false,
    pendingAction: null,
    batch: live ? { ...batch, status: "error", error: message, currentId: String(payload.page_id || batch.currentId || "") } : batch,
  });
  const pageId = String(payload.page_id || "");
  if (pageId) updatePage(pageId, { status: "error", error: message });
  setBanner("job", { text: message });
}

function batchIsLive() {
  const status = (getState().batch || {}).status;
  return status === "running" || status === "paused";
}

function stopJobs() {
  cancelJobs().then((data) => {
    onCancelled();
    if (data) patch({ jobs: data });
  }).catch(showError);
}

function onCancelled() {
  const pages = getState().pages.map((page) => (
    page.status === "running" || page.status === "queued"
      ? { ...page, status: "idle", progress: 0, stage: "" }
      : page
  ));
  patch({
    busy: false,
    pendingAction: null,
    pages,
    job: { stage: "", index: 0, total: 0, pageId: "" },
    batch: { status: "idle", startedAt: null, done: 0, error: "", currentId: "" },
  });
}

function movePage(delta) {
  const state = getState();
  if (!state.pages.length) return;
  let index = state.pages.findIndex((page) => page.id === state.activePageId);
  if (index < 0) index = 0;
  index = Math.max(0, Math.min(state.pages.length - 1, index + delta));
  const id = state.pages[index].id;
  setAnchor(id);
  selectPages([id], id, id);
}

function nudge(key, mods) {
  const id = getState().selectedRegionId;
  if (id == null) return;
  const step = mods.shift ? 10 : 1;
  editDocument((document) => {
    const region = findRegion(document, id);
    if (!region) return;
    let [x, y, width, height] = region.bbox;
    if (mods.alt) {
      if (key === "ArrowRight") width += step;
      if (key === "ArrowLeft") width -= step;
      if (key === "ArrowDown") height += step;
      if (key === "ArrowUp") height -= step;
    } else {
      if (key === "ArrowRight") x += step;
      if (key === "ArrowLeft") x -= step;
      if (key === "ArrowDown") y += step;
      if (key === "ArrowUp") y -= step;
    }
    const size = getState().imageSize;
    region.bbox = clampBox([x, y, width, height], size.w, size.h);
    region.edited = true;
  });
}

function deleteRegion() {
  const id = getState().selectedRegionId;
  if (id == null) return;
  editDocument((document) => {
    document.regions = document.regions.filter((region) => String(region.id) !== String(id));
  });
  selectRegion(null);
}

function escape() {
  if (menuOpen() && closeMenu()) return;
  if (closeTop()) return;
  if (settingsOpen()) {
    document.querySelector("[data-role='settings-cancel']").click();
    return;
  }
  if (isWizard()) return;
  if (getState().busy || batchIsLive()) {
    stopJobs();
    return;
  }
  if (getState().selectedRegionId != null) selectRegion(null);
}

function onDrag(event) {
  event.preventDefault();
  document.querySelector("[data-role='empty-drop']")?.classList.add("is-dragover");
}

async function onDrop(event) {
  event.preventDefault();
  document.querySelector("[data-role='empty-drop']")?.classList.remove("is-dragover");
  const transfer = event.dataTransfer;
  if (!transfer) return;
  const paths = collectPaths(transfer);
  const looksLikeFiles = (transfer.files && transfer.files.length) || [...(transfer.items || [])].some((item) => item.kind === "file");
  if (!paths.length) {
    if (looksLikeFiles) setBanner("drop", { text: DROP_HINT });
    return;
  }
  try {
    const data = await dropPaths(paths);
    takeProject(data);
    setBanner("drop", null);
  } catch (error) {
    showError(error);
  }
}

function collectPaths(transfer) {
  const paths = [];
  const files = transfer.files ? [...transfer.files] : [];
  files.forEach((file) => {
    if (file && file.pywebviewFullPath) paths.push(file.pywebviewFullPath);
  });
  const items = transfer.items ? [...transfer.items] : [];
  items.forEach((item) => {
    if (item && item.pywebviewFullPath) paths.push(item.pywebviewFullPath);
    const file = item.getAsFile ? item.getAsFile() : null;
    if (file && file.pywebviewFullPath) paths.push(file.pywebviewFullPath);
  });
  if (transfer.pywebviewFullPath) paths.push(transfer.pywebviewFullPath);
  return [...new Set(paths.filter(Boolean))];
}

function closeMenus() {
  document.querySelectorAll("details.menu[open]").forEach((menu) => {
    menu.open = false;
  });
}

function showError(error) {
  setBanner("error", { text: error.message || "Ошибка запроса" });
}

function savedWord(count) {
  const abs = Math.abs(count) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return "страниц";
  if (last === 1) return "страница";
  if (last >= 2 && last <= 4) return "страницы";
  return "страниц";
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

function settledCount(pages) {
  return (pages || []).filter((page) => page.status === "done" || page.status === "edited" || page.status === "offline").length;
}

function batchState(state) {
  return {
    pages: (state.pages || []).map((page) => ({
      ...page,
      thumb: imageUrl(page.id, "thumb", page.version),
      overflow: page.overflow || (page.id === state.activePageId && (state.document?.regions || []).some((region) => region.overflow)),
    })),
    activePageId: state.activePageId,
    batch: state.batch || { status: "idle" },
  };
}

const batchActions = {
  pause: () => pauseJobs().then((data) => patch({
    batch: { ...getState().batch, status: "paused", pausedAt: Date.now() },
    jobs: data,
  })).catch(showError),
  resume: () => {
    const batch = getState().batch || {};
    const pausedFor = batch.pausedAt ? Date.now() - batch.pausedAt : 0;
    return resumeJobs().then((data) => patch({
      batch: {
        ...batch,
        status: "running",
        error: "",
        startedAt: (batch.startedAt || Date.now()) + pausedFor,
        pausedAt: null,
      },
      jobs: data,
      busy: true,
    })).catch(showError);
  },
  retryErrors: () => retryErrors().then(() => patch({
    batch: { ...getState().batch, status: "running", error: "", startedAt: Date.now() },
    busy: true,
  })).catch(showError),
  importFolder: () => importChapterFolder(),
  openGlossary: () => openGlossary(),
  focusPage: (pageId) => selectPages([pageId], pageId, pageId),
};

async function importChapterFolder() {
  const chapters = await confirm({
    title: "Импорт папки",
    text: "Каждая подпапка — глава?",
    ok: "Да",
    cancel: "Нет",
  });
  try {
    const picked = await pickFolder();
    if (!picked || picked.cancelled || !picked.path) return;
    const data = await importSources({
      path: picked.path,
      recursive: true,
      chapter_mode: chapters ? "subdir" : "flat",
    });
    takeProject(data);
  } catch (error) {
    showError(error);
  }
}

function syncSfx(settings) {
  const mode = settings && settings.sfx_mode === "replace" ? "replace" : "skip";
  document.querySelectorAll("input[name='sfx-mode']").forEach((input) => {
    if (document.activeElement === input) return;
    input.checked = input.value === mode;
  });
}

async function saveSfxMode(mode) {
  const value = mode === "replace" ? "replace" : "skip";
  const body = settingsForSave({ ...getState().settings, sfx_mode: value, translate_sfx: value === "replace" });
  try {
    const saved = await putSettings(body);
    const settings = saved && saved.settings ? { ...body, ...saved.settings } : body;
    patch({ settings });
  } catch (error) {
    showError(error);
    syncSfx(getState().settings);
  }
}

function copyRegionStyle() {
  const state = getState();
  const region = findRegion(state.document, state.selectedRegionId);
  if (!region || !region.style) return;
  copiedStyle = JSON.parse(JSON.stringify(region.style));
}

function pasteRegionStyle() {
  if (!copiedStyle) return;
  const style = JSON.parse(JSON.stringify(copiedStyle));
  const id = getState().selectedRegionId;
  if (id == null || id === "") return;
  editDocument((document) => {
    const region = findRegion(document, id);
    if (!region) return;
    region.style = { ...(region.style || {}), ...style };
    if (style.warp) region.style.warp = { ...(region.style.warp || {}), ...style.warp };
  });
}

function focusNextProblem() {
  const pages = getState().pages;
  if (!pages.length) return;
  const problem = (page) => page.status === "error" || page.status === "offline" || page.overflow;
  const start = pages.findIndex((page) => page.id === getState().activePageId);
  for (let step = 1; step <= pages.length; step += 1) {
    const page = pages[(start + step + pages.length) % pages.length];
    if (problem(page)) {
      selectPages([page.id], page.id, page.id);
      return;
    }
  }
}

function notifyBatchFinished() {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    new Notification("Прогон завершён");
  } catch (error) {
    /* разрешение есть, но система не показала окно */
  }
}

async function syncJobs() {
  try {
    const data = await jobs();
    const batch = { ...(getState().batch || {}) };
    if (data && data.paused) batch.status = batch.status === "error" ? "error" : "paused";
    else if (data && data.unfinished) {
      batch.status = "running";
      batch.startedAt = batch.startedAt || Date.now();
    }
    patch({ jobs: data, batch });
  } catch (error) {
    /* очередь ещё не нужна на пустом окне */
  }
}

async function refreshRemote() {
  try {
    const data = await remoteStatus();
    patch({
      remote: {
        enabled: Boolean(data && data.enabled),
        clients: Number(data && data.clients) || 0,
        addresses: (data && data.addresses) || [],
        pairing_code: (data && data.pairing_code) || "",
        devices: (data && data.devices) || [],
        recent: (data && data.recent) || [],
        loaded: true,
        error: "",
      },
    });
  } catch (error) {
    patch({
      remote: {
        enabled: false,
        clients: 0,
        addresses: [],
        pairing_code: "",
        devices: [],
        recent: [],
        loaded: true,
        error: error.message || "Нет ответа",
      },
    });
  }
}

start();
