/* Просмотрщик: масштаб, шторка, рамки, кисть и ластик. */

import { imageUrl } from "./api.js";
import { MeshPreviewRenderer } from "./mesh_preview_renderer.js";
import {
  brushModeFromButton,
  editorSessionToWire,
  fitWidthScale,
  normalizeEditorSession,
  polylineModeFromButton,
  resolveActivePageId,
} from "./editor_session.js";
import { maskDraftAction, paintStrokeOnMask } from "./mask_draft.js";
import {
  blankRegion,
  clampBox,
  editDocument,
  findRegion,
  getState,
  isDirty,
  isReadyStatus,
  nextRegionId,
  patch,
  sameId,
  selectRegion,
  stageLabel,
  subscribe,
} from "./state.js";
import { isSpaceDown } from "./keys.js";
import { isValidMesh } from "./text_mesh.js";

const TOOLS = ["select", "region", "brush", "polyline", "hand"];
const VIEWS = ["original", "result", "compare"];
const ZOOM_MIN_PERCENT = 10;
const ZOOM_MAX_PERCENT = 200;
const ZOOM_STEP_PERCENT = 5;
const MASK_DRAW_TOOLS = new Set(["brush", "polyline"]);
const BRUSH_SIZE_TOOLS = new Set(["brush"]);
/** Превью добавления в маску. */
const MASK_PAINT_COLOR = "#16a34a";
/** Превью удаления из маски (ластик). */
const MASK_ERASE_COLOR = "#2563eb";

let stageHost;
let stage;
let frame;
let baseImage;
let curtain;
let curtainImage;
let maskImage;
let boxes;
let bar;
let labels;
let progress;
let progressText;
let strokeLayer;
let cursor;
let sizeLabel;
let zoomLabel;
let steps;
let placeholder;
let maskLocal;
let natural = { w: 0, h: 0 };
let drag = null;
let selectedWarpRegionId = "";
let selectedWarpNodes = new Set();
let lastWarpPointer = null;
let previewImage = null;
let previewUrl = "";
let meshPreviewCanvas = null;
let meshPreviewRenderer = null;
let meshBaseUrl = "";
let meshBaseImage = null;
let meshBaseRegion = null;
let spaceDown = false;
let seenPageId = "";
let scrollHome = false;
/** Локальная маска на время deferApply / ожидания серверного обновления после «Готово». */
let maskDraft = null;
/** Черновик ломаной: вершины + точка под курсором для резинки. */
let polyDraft = null;
/** Отложенное восстановление scroll после layout. */
let pendingScroll = null;

export function init() {
  stageHost = document.querySelector("[data-role='stage-host']");
  stage = document.querySelector("[data-role='stage']");
  frame = document.querySelector("[data-role='frame']");
  baseImage = document.querySelector("[data-role='img-base']");
  curtain = document.querySelector("[data-role='curtain']");
  curtainImage = document.querySelector("[data-role='img-curtain']");
  maskImage = document.querySelector("[data-role='img-mask']");
  boxes = document.querySelector("[data-role='boxes']");
  previewImage = document.querySelector("[data-role='style-preview']");
  meshPreviewCanvas = document.querySelector("[data-role='mesh-preview']");
  meshPreviewRenderer = new MeshPreviewRenderer(meshPreviewCanvas, (message) => {
    if (previewImage && previewImage.src) previewImage.hidden = false;
    document.dispatchEvent(new CustomEvent("ilt-banner", { detail: { id: "mesh-renderer", text: message } }));
  });
  bar = document.querySelector("[data-role='curtain-bar']");
  labels = document.querySelectorAll("[data-role='curtain-label']");
  progress = document.querySelector("[data-role='frame-progress']");
  progressText = document.querySelector("[data-role='frame-progress-text']");
  strokeLayer = document.querySelector("[data-role='stroke-layer']");
  cursor = document.querySelector("[data-role='brush-cursor']");
  sizeLabel = document.querySelector("[data-role='brush-size-value']");
  zoomLabel = document.querySelector("[data-role='zoom-value']");
  steps = document.querySelector("[data-role='steps']");
  placeholder = document.querySelector("[data-role='result-placeholder']");
  maskLocal = document.querySelector("[data-role='mask-local']");

  const range = document.querySelector("[data-role='brush-size']");
  range.addEventListener("input", () => {
    patch({ brushSize: Number(range.value) || 1 });
  });
  const sizeStrip = document.querySelector("[data-role='brush-size-label']");
  sizeStrip?.addEventListener("wheel", (event) => {
    event.preventDefault();
    nudgeBrush(event.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  document.querySelector("[data-role='zoom-out']").addEventListener("click", () => stepZoom(-1));
  document.querySelector("[data-role='zoom-in']").addEventListener("click", () => stepZoom(1));
  document.querySelector("[data-role='zoom-value']").addEventListener("click", () => setZoom("fit"));
  document.querySelector("[data-role='zoom-label']")?.addEventListener("click", () => setZoom("fit"));
  document.querySelector("[data-role='zoom-fit-width']")?.addEventListener("click", () => setZoom("fit-width"));
  document.querySelector("[data-role='page-prev']").addEventListener("click", () => turnPage(-1));
  document.querySelector("[data-role='page-next']").addEventListener("click", () => turnPage(1));
  document.querySelector("[data-role='undo']").addEventListener("click", () => document.dispatchEvent(new CustomEvent("ilt-undo")));
  document.querySelector("[data-role='redo']").addEventListener("click", () => document.dispatchEvent(new CustomEvent("ilt-redo")));

  bindRadios("[data-role='view-group']", "view", VIEWS);
  bindRadios("[data-role='tool-group']", "tool", TOOLS);
  document.querySelector("[data-role='layer-boxes']").addEventListener("click", () => {
    patch({ showBoxes: !getState().showBoxes });
  });
  document.querySelector("[data-role='layer-mask']").addEventListener("click", () => {
    patch({ showMask: !getState().showMask });
  });

  frame.addEventListener("pointerdown", onPointerDown);
  frame.addEventListener("mousedown", (event) => {
    if (event.button === 1) event.preventDefault();
  });
  frame.addEventListener("dblclick", onDoubleClick);
  frame.addEventListener("pointermove", onPointerMove);
  frame.addEventListener("pointerup", onPointerUp);
  frame.addEventListener("pointercancel", (event) => onPointerUp(event, true));
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !drag) return;
    if (drag.kind === "warp" && drag.meshV2) {
      event.preventDefault();
      event.stopImmediatePropagation();
      drag = null;
      finishMeshDraft();
      renderBoxes(getState());
      return;
    }
    if (drag.kind !== "text-position") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    cancelTextPositionDrag();
  }, true);
  frame.addEventListener("pointerleave", () => {
    cursor.hidden = true;
  });
  stage.addEventListener("wheel", onWheel, { passive: false });
  stage.addEventListener("auxclick", (event) => event.preventDefault());
  stage.addEventListener("scroll", rememberCenter);
  baseImage.addEventListener("load", onImageLoad);
  baseImage.addEventListener("error", onBaseError);
  curtainImage.addEventListener("load", onOriginalLoad);
  maskImage.addEventListener("load", onMaskImageLoad);
  maskImage.addEventListener("error", () => maskImage.classList.add("is-missing"));
  window.addEventListener("resize", layout);
  if (window.ResizeObserver) new ResizeObserver(() => layout()).observe(stage);
  subscribe(sync);
  sync(getState());
}

export function setSpace(down) {
  spaceDown = down;
  syncPanCursor();
}

export function viewCenter() {
  const state = getState();
  if (!natural.w || !frame) return { x: natural.w / 2 || 40, y: natural.h / 2 || 20, w: natural.w, h: natural.h };
  const frameRect = frame.getBoundingClientRect();
  const stageRect = stage.getBoundingClientRect();
  const left = Math.max(stageRect.left, frameRect.left);
  const right = Math.min(stageRect.right, frameRect.right);
  const top = Math.max(stageRect.top, frameRect.top);
  const bottom = Math.min(stageRect.bottom, frameRect.bottom);
  const x = frameRect.width ? ((left + right) / 2 - frameRect.left) / frameRect.width * natural.w : natural.w / 2;
  const y = frameRect.height ? ((top + bottom) / 2 - frameRect.top) / frameRect.height * natural.h : natural.h / 2;
  return { x, y, w: natural.w || state.imageSize.w, h: natural.h || state.imageSize.h };
}

export function setZoom(mode) {
  patch({ zoom: mode });
  if (mode === "fit" || mode === "fit-width") {
    stage.scrollLeft = 0;
    stage.scrollTop = 0;
  }
}

/** Снимок UI-сессии для сохранения в пакет. */
export function captureEditorSession() {
  const state = getState();
  return editorSessionToWire({
    active_page_id: state.activePageId || "",
    zoom: state.zoom,
    scroll_left: stage ? stage.scrollLeft : 0,
    scroll_top: stage ? stage.scrollTop : 0,
  });
}

/** Восстановить страницу / zoom / scroll из пакета или ответа save. */
export function applyEditorSession(raw, { selectPages } = {}) {
  const session = normalizeEditorSession(raw);
  if (!session) return;
  const state = getState();
  const pageId = resolveActivePageId(state.pages, session.activePageId);
  if (pageId && pageId !== state.activePageId && typeof selectPages === "function") {
    selectPages([pageId], pageId, pageId);
  }
  if (session.zoom !== undefined) patch({ zoom: session.zoom });
  pendingScroll = { left: session.scrollLeft, top: session.scrollTop };
  window.requestAnimationFrame(() => {
    layout();
    applyPendingScroll();
  });
}

function applyPendingScroll() {
  if (!pendingScroll || !stage) return;
  const { left, top } = pendingScroll;
  pendingScroll = null;
  stage.scrollLeft = left;
  stage.scrollTop = top;
}

export function setStylePreview(preview) {
  if (!previewImage) return;
  if (previewUrl && previewUrl !== (preview && preview.url)) URL.revokeObjectURL(previewUrl);
  if (!preview || !preview.url) {
    previewUrl = "";
    previewImage.hidden = true;
    previewImage.removeAttribute("src");
    return;
  }
  previewUrl = preview.url;
  previewImage.hidden = false;
  previewImage.onload = () => {
    if (!natural.w || !natural.h) return;
    previewImage.style.left = pct(preview.x || 0, natural.w);
    previewImage.style.top = pct(preview.y || 0, natural.h);
    previewImage.style.width = pct(previewImage.naturalWidth || 1, natural.w);
    previewImage.style.height = pct(previewImage.naturalHeight || 1, natural.h);
  };
  previewImage.src = preview.url;
}

export function setMeshPreviewBase(preview, region) {
  if (meshBaseUrl && meshBaseUrl !== (preview && preview.url)) URL.revokeObjectURL(meshBaseUrl);
  meshBaseUrl = preview && preview.url ? preview.url : "";
  meshBaseImage = null;
  meshBaseRegion = region || null;
  if (!meshBaseUrl || !meshPreviewRenderer) return;
  const image = new Image();
  image.onload = () => {
    if (meshBaseUrl !== preview.url) return;
    meshBaseImage = image;
    meshPreviewRenderer.setLayer(image);
  };
  image.src = meshBaseUrl;
}

export function clearMeshPreviewBase() {
  if (meshBaseUrl) URL.revokeObjectURL(meshBaseUrl);
  meshBaseUrl = "";
  meshBaseImage = null;
  meshBaseRegion = null;
  meshPreviewRenderer?.hide();
}

function drawMeshDraft(region, mesh) {
  if (!meshBaseImage || !meshBaseRegion || !meshPreviewRenderer) return false;
  if (!sameId(meshBaseRegion.id, region.id) || meshBaseImage.naturalWidth < 1) return false;
  const anchorBox = region.bubble_bbox || region.bbox;
  const style = region.style || {};
  const result = meshPreviewRenderer.render({
    mesh,
    bbox: region.bbox,
    origin: [meshBaseRegion.originX, meshBaseRegion.originY],
    rotation: Number(style.rotation) || 0,
    textPosition: region.text_position,
    anchor: [anchorBox[0] + anchorBox[2] / 2, anchorBox[1] + anchorBox[3] / 2],
    pageSize: [natural.w, natural.h],
  });
  if (result && previewImage) previewImage.hidden = true;
  return result;
}

function finishMeshDraft() {
  meshPreviewRenderer?.hide();
  if (previewImage && previewImage.src) previewImage.hidden = false;
}

export function nudgeBrush(delta) {
  const next = Math.max(1, Math.min(64, (getState().brushSize || 12) + delta));
  patch({ brushSize: next });
}

export function hasPolylineDraft() {
  return Boolean(polyDraft && polyDraft.points.length);
}

/** Отменить черновик лассо. True, если что-то сбросили. */
export function cancelPolylineDraft() {
  if (!polyDraft) return false;
  polyDraft = null;
  if (strokeLayer) strokeLayer.innerHTML = "";
  return true;
}

/** Завершить лассо заливкой полигона. True, если штрих записан. */
export function commitPolylineDraft() {
  if (!polyDraft || polyDraft.points.length < 3) {
    cancelPolylineDraft();
    return false;
  }
  const points = polyDraft.points.map((point) => [Math.round(point[0]), Math.round(point[1])]);
  const mode = polyDraft.mode === "erase_fill" ? "erase_fill" : "fill";
  polyDraft = null;
  if (strokeLayer) strokeLayer.innerHTML = "";
  editDocument((document) => {
    document.strokes.push({ mode, radius: 1, points });
  }, { deferApply: true });
  return true;
}

function bindRadios(selector, key, order) {
  const group = document.querySelector(selector);
  group.addEventListener("click", (event) => {
    const button = event.target.closest("[data-value]");
    if (!button || button.disabled) return;
    patch({ [key]: button.dataset.value });
  });
  group.addEventListener("keydown", (event) => {
    const buttons = [...group.querySelectorAll("[data-value]")].filter((button) => !button.disabled);
    const index = buttons.indexOf(document.activeElement);
    if (index < 0) return;
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % buttons.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + buttons.length) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next < 0) return;
    event.preventDefault();
    patch({ [key]: buttons[next].dataset.value });
    buttons[next].focus();
  });
  void order;
}

function sync(state) {
  if (state.tool === "eraser") {
    patch({ tool: "brush" });
    return;
  }
  const page = state.pages.find((item) => item.id === state.activePageId);
  const enabled = Boolean(page);
  document.querySelectorAll("[data-view-control]").forEach((node) => {
    node.disabled = !enabled;
  });
  document.querySelector("[data-role='undo']").disabled = !state.undoCount;
  document.querySelector("[data-role='redo']").disabled = !state.redoCount;
  const range = document.querySelector("[data-role='brush-size']");
  const brushToggle = document.querySelector("[data-role='brush-size-toggle']");
  const brushPop = document.getElementById("brush-size-pop");
  const brushOn = BRUSH_SIZE_TOOLS.has(state.tool);
  if (brushToggle) brushToggle.hidden = !brushOn;
  if (!brushOn && brushPop) {
    brushPop.hidden = true;
    if (brushToggle) brushToggle.setAttribute("aria-expanded", "false");
  }
  if (state.tool !== "polyline" && polyDraft) {
    polyDraft = null;
    if (strokeLayer) strokeLayer.innerHTML = "";
  }
  if (document.activeElement !== range) range.value = String(state.brushSize);
  if (sizeLabel) sizeLabel.textContent = String(state.brushSize);

  setRadio("[data-role='view-group']", state.view);
  setRadio("[data-role='tool-group']", state.tool);
  const boxesButton = document.querySelector("[data-role='layer-boxes']");
  const maskButton = document.querySelector("[data-role='layer-mask']");
  boxesButton.setAttribute("aria-pressed", state.showBoxes ? "true" : "false");
  maskButton.setAttribute("aria-pressed", state.showMask ? "true" : "false");

  if (stageHost) stageHost.hidden = !enabled;
  stage.hidden = !enabled;
  steps.hidden = !enabled;
  syncPageNav(state, enabled);
  if (!enabled) return;

  let home = false;
  if (page.id !== seenPageId) {
    seenPageId = page.id;
    clearMaskDraft();
    cancelPolylineDraft();
    home = state.zoom !== "fit" && state.zoom !== "fit-width";
    scrollHome = home;
    if (home) pinScroll();
  }

  const version = state.document?.version || page.version || 0;
  setSrc(baseImage, page, state.view === "original" ? "original" : "result", version);
  setSrc(curtainImage, page, "original", version);
  setSrc(maskImage, page, "mask", version);
  baseImage.alt = `${state.view === "original" ? "Оригинал" : "Результат"} страницы ${page.name}`;
  frame.classList.toggle("frame--mask", state.showMask);
  syncMaskDraft(state, page);
  const compare = state.view === "compare";
  curtain.hidden = !compare;
  bar.hidden = !compare;
  labels.forEach((label) => {
    label.hidden = !compare;
  });
  if (!drag || drag.kind !== "curtain") {
    curtain.style.width = `${state.curtain * 100}%`;
    bar.style.left = `${state.curtain * 100}%`;
  }
  renderBoxes(state);
  renderProgress(state, page);
  renderSteps(state, page);
  stage.classList.toggle(
    "is-cross",
    (state.tool === "region" || MASK_DRAW_TOOLS.has(state.tool)) && !spaceDown,
  );
  syncPanCursor();
  layout();
  if (home) pinScroll();
}

function syncPageNav(state, enabled) {
  const index = state.pages.findIndex((item) => item.id === state.activePageId);
  const prev = document.querySelector("[data-role='page-prev']");
  const next = document.querySelector("[data-role='page-next']");
  if (prev) prev.disabled = !enabled || index <= 0;
  if (next) next.disabled = !enabled || index < 0 || index >= state.pages.length - 1;
}

function syncPanCursor() {
  const hand = spaceDown || getState().tool === "hand";
  stage.classList.toggle("is-pan", hand && !(drag && drag.kind === "pan"));
}

function turnPage(delta) {
  document.dispatchEvent(new CustomEvent("ilt-page", { detail: delta }));
}

function pinScroll() {
  stage.scrollTop = 0;
  stage.scrollLeft = 0;
}

function setRadio(selector, value) {
  const group = document.querySelector(selector);
  const buttons = [...group.querySelectorAll("[data-value]")];
  buttons.forEach((button) => {
    const on = button.dataset.value === value;
    button.setAttribute("aria-checked", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  });
  if (!buttons.some((button) => button.tabIndex === 0) && buttons[0]) buttons[0].tabIndex = 0;
}

function setSrc(image, page, kind, version) {
  if (image === baseImage && image.dataset.pageId && image.dataset.pageId !== page.id) {
    // Старый кадр не должен мигать на новой странице, пока грузится новый.
    showResultGap(true);
  }
  if (image === baseImage && kind === "result" && !isReadyStatus(page.status)) {
    // Пока идёт повторная вёрстка — оставляем прежний результат, но только
    // если это та же страница: иначе на новой странице висел бы чужой кадр.
    const samePage = image.dataset.pageId === page.id;
    if (samePage && baseImage.getAttribute("src") && !baseImage.hidden) {
      showResultGap(false);
      return;
    }
    showResultGap(true);
    return;
  }
  if (image === baseImage) showResultGap(false);
  const url = imageUrl(page.id, kind, version);
  image.dataset.pageId = page.id;
  if (image.dataset.url === url) return;
  image.dataset.url = url;
  if (image === maskImage) image.classList.remove("is-missing");
  image.src = url;
}

function onMaskImageLoad() {
  maskImage.classList.remove("is-missing");
  const state = getState();
  if (state.deferredApply || maskDraft) syncMaskDraft(state, state.pages.find((item) => item.id === state.activePageId));
}

function clearMaskDraft() {
  maskDraft = null;
  if (maskLocal) {
    maskLocal.hidden = true;
    if (maskLocal.width && maskLocal.height) {
      const ctx = maskLocal.getContext("2d");
      ctx?.clearRect(0, 0, maskLocal.width, maskLocal.height);
    }
  }
  frame?.classList.remove("frame--mask-draft");
}

function syncMaskDraft(state, page) {
  if (!maskLocal || !frame) return;
  const pageId = state.activePageId || "";
  if (!pageId || !page) {
    clearMaskDraft();
    return;
  }
  if (!natural.w || !natural.h) return;
  const busy = !isReadyStatus(page.status) || isDirty(pageId);
  const action = maskDraftAction({
    deferredApply: state.deferredApply,
    pageId,
    draftPageId: maskDraft?.pageId || "",
    pageBusy: busy,
  });
  if (action === "paint") {
    if (!maskDraft || maskDraft.pageId !== pageId) {
      maskDraft = { pageId, waitingServer: false };
    } else {
      maskDraft.waitingServer = false;
    }
    paintLocalMask(state.document?.strokes || []);
    return;
  }
  if (action === "wait") {
    maskDraft.waitingServer = true;
    maskLocal.hidden = false;
    frame.classList.add("frame--mask-draft");
    return;
  }
  clearMaskDraft();
}

function paintLocalMask(strokes) {
  if (!maskLocal || !natural.w || !natural.h) return;
  if (maskLocal.width !== natural.w || maskLocal.height !== natural.h) {
    maskLocal.width = natural.w;
    maskLocal.height = natural.h;
  }
  const ctx = maskLocal.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, natural.w, natural.h);
  if (
    maskImage
    && maskImage.complete
    && maskImage.naturalWidth > 0
    && !maskImage.classList.contains("is-missing")
  ) {
    try {
      ctx.drawImage(maskImage, 0, 0, natural.w, natural.h);
    } catch (_error) {
      /* same-origin; ignore rare decode races */
    }
  }
  for (const stroke of strokes) paintStrokeOnMask(ctx, stroke);
  maskLocal.hidden = false;
  frame.classList.add("frame--mask-draft");
}

function showResultGap(on) {
  if (!placeholder) return;
  placeholder.hidden = !on;
  baseImage.hidden = on;
  if (!on) return;
  baseImage.removeAttribute("src");
  baseImage.dataset.url = "";
}

function onBaseError() {
  const view = getState().view;
  if (view === "result" || view === "compare") {
    showResultGap(true);
    applyOriginalNatural();
  }
}

function onImageLoad() {
  const state = getState();
  const page = state.pages.find((item) => item.id === state.activePageId);
  if (page && !currentSrcIsPage(baseImage, page.id)) return;
  natural = { w: baseImage.naturalWidth || 0, h: baseImage.naturalHeight || 0 };
  patch({ imageSize: { ...natural } });
  if (scrollHome) {
    pinScroll();
    window.requestAnimationFrame(pinScroll);
    scrollHome = false;
  }
  layout();
  applyPendingScroll();
  if (state.deferredApply || maskDraft) {
    syncMaskDraft(state, state.pages.find((item) => item.id === state.activePageId));
  }
}

/** Оригинал задаёт размер листа, даже когда result ещё не готов. */
function onOriginalLoad() {
  const state = getState();
  const page = state.pages.find((item) => item.id === state.activePageId);
  if (!page || !currentSrcIsPage(curtainImage, page.id)) return;
  if (!baseImage.hidden && baseImage.naturalWidth) return;
  applyOriginalNatural();
}

function currentSrcIsPage(image, pageId) {
  const source = image.currentSrc || image.src || "";
  return !pageId || source.includes(encodeURIComponent(pageId));
}

function applyOriginalNatural() {
  const state = getState();
  const page = state.pages.find((item) => item.id === state.activePageId);
  if (!page || !currentSrcIsPage(curtainImage, page.id)) return;
  if (!curtainImage.naturalWidth || !curtainImage.naturalHeight) return;
  natural = { w: curtainImage.naturalWidth, h: curtainImage.naturalHeight };
  patch({ imageSize: { ...natural } });
  layout();
  applyPendingScroll();
  if (state.deferredApply || maskDraft) syncMaskDraft(state, page);
}

function fitScale() {
  if (!natural.w || !natural.h) return 1;
  const width = Math.max(1, stage.clientWidth - 16);
  const height = Math.max(1, stage.clientHeight - 16);
  return Math.min(width / natural.w, height / natural.h);
}

function currentScale() {
  const zoom = getState().zoom;
  if (zoom === "fit") return fitScale();
  if (zoom === "fit-width") return fitWidthScale(stage.clientWidth, natural.w, 16);
  return Number(zoom) || 1;
}

function layout() {
  if (!frame || stage.hidden || !natural.w) return;
  const scale = currentScale();
  const width = Math.max(1, Math.round(natural.w * scale));
  const height = Math.max(1, Math.round(natural.h * scale));
  if (stage.style.getPropertyValue("--frame-w") === `${width}px` && stage.style.getPropertyValue("--frame-h") === `${height}px`) {
    updateZoomLabel(scale);
    return;
  }
  stage.style.setProperty("--frame-w", `${width}px`);
  stage.style.setProperty("--frame-h", `${height}px`);
  updateZoomLabel(scale);
}

function updateZoomLabel(scale) {
  const zoom = getState().zoom;
  let text = `${Math.round(scale * 100)} %`;
  if (zoom === "fit") text = "Вписать";
  else if (zoom === "fit-width") text = "По ширине";
  if (zoomLabel.textContent !== text) zoomLabel.textContent = text;
  const status = document.querySelector("[data-role='zoom-label']");
  if (status && status.textContent !== text) status.textContent = text;
  const fitWidthBtn = document.querySelector("[data-role='zoom-fit-width']");
  if (fitWidthBtn) fitWidthBtn.setAttribute("aria-pressed", zoom === "fit-width" ? "true" : "false");
}

function zoomSteps() {
  const steps = [];
  for (let percent = ZOOM_MIN_PERCENT; percent <= ZOOM_MAX_PERCENT; percent += ZOOM_STEP_PERCENT) {
    steps.push(percent / 100);
  }
  return steps;
}

function zoomAt(scale, direction) {
  const steps = zoomSteps();
  if (direction > 0) return steps.find((item) => item > scale + 0.001) || ZOOM_MAX_PERCENT / 100;
  return [...steps].reverse().find((item) => item < scale - 0.001) || ZOOM_MIN_PERCENT / 100;
}

function stepZoom(direction) {
  patch({ zoom: zoomAt(currentScale(), direction) });
}

function onWheel(event) {
  if (!event.ctrlKey || stage.hidden) return;
  event.preventDefault();
  const next = zoomAt(currentScale(), event.deltaY < 0 ? 1 : -1);
  const rect = frame.getBoundingClientRect();
  const u = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
  const v = rect.height ? (event.clientY - rect.top) / rect.height : 0.5;
  patch({ zoom: next });
  layout();
  const nextRect = frame.getBoundingClientRect();
  stage.scrollLeft += nextRect.left + u * nextRect.width - event.clientX;
  stage.scrollTop += nextRect.top + v * nextRect.height - event.clientY;
}

function renderBoxes(state) {
  boxes.hidden = !state.showBoxes;
  if (!sameId(selectedWarpRegionId, state.selectedRegionId)) {
    selectedWarpRegionId = state.selectedRegionId || "";
    selectedWarpNodes = new Set();
  }
  if (!state.showBoxes || !natural.w) {
    boxes.innerHTML = "";
    return;
  }
  if (drag && (drag.kind === "move" || drag.kind === "resize" || drag.kind === "rotate" || drag.kind === "warp")) return;
  const selected = state.selectedRegionId;
  boxes.innerHTML = (state.document?.regions || []).map((region, index) => {
    const [x, y, w, h] = region.bbox;
    const classes = ["box"];
    const kind = region.type || region.block_type;
    const isSelected = sameId(region.id, selected);
    if (isSelected) classes.push("box--selected");
    if (kind === "sfx") classes.push("box--sfx");
    if (region.skip) classes.push("box--skipped");
    if (region.overflow) classes.push("box--overflow");
    const flags = [];
    if (kind === "sfx") flags.push("звук");
    if (region.skip) flags.push("пропущен");
    if (region.overflow) flags.push("не влез");
    const flag = flags.length ? `<span class="box__flag">${flags.join(" · ")}</span>` : "";
    const handles = isSelected ? `${rotateHandle()}${warpHandles(region)}` : "";
    return `<div class="${classes.join(" ")}" data-box-id="${escapeAttr(region.id)}" style="left:${pct(x, natural.w)};top:${pct(y, natural.h)};width:${pct(w, natural.w)};height:${pct(h, natural.h)}"><span class="box__num">${index + 1}</span>${flag}${handles}</div>`;
  }).join("");
}

function rotateHandle() {
  return '<button type="button" class="box__rotate" data-style-handle="rotate" aria-label="Повернуть регион"></button>';
}

function warpHandles(region) {
  const warp = region.style && region.style.warp;
  if (!warp) return "";
  const [, , w, h] = region.bbox;
  let points = null;
  if (warp.kind === "perspective") points = Array.isArray(warp.quad) ? warp.quad : defaultQuad(w, h);
  else if (warp.kind === "mesh") points = Array.isArray(warp.mesh) ? warp.mesh : defaultMesh(w, h);
  else return "";
  return `<svg class="box__grid" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${warpLines(points, warp.kind)}</svg>` + points.map((point, index) => {
    const left = w ? (Number(point[0]) / w) * 100 : 0;
    const top = h ? (Number(point[1]) / h) * 100 : 0;
    const selected = sameId(selectedWarpRegionId, region.id) && selectedWarpNodes.has(index);
    return `<button type="button" class="box__point${selected ? " is-group-selected" : ""}" data-style-handle="point" data-index="${index}" style="left:${left}%;top:${top}%" aria-pressed="${selected}" aria-label="Точка ${index + 1}"></button>`;
  }).join("");
}

/** Связи управляющих точек: четыре строки и столбца либо контур перспективы. */
function warpLines(points, kind) {
  const lines = kind === "mesh"
    ? [...Array.from({ length: 4 }, (_, r) => points.slice(r * 4, r * 4 + 4)),
       ...Array.from({ length: 4 }, (_, c) => [points[c], points[c + 4], points[c + 8], points[c + 12]])]
    : [[...points, points[0]]];
  return lines.map((line) => `<polyline points="${line.map((p) => `${Number(p[0]) || 0},${Number(p[1]) || 0}`).join(" ")}"/>`).join("");
}

function defaultQuad(w, h) {
  return [[0, 0], [w, 0], [w, h], [0, h]];
}

function defaultMesh(w, h) {
  const points = [];
  for (let row = 0; row < 4; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      points.push([(col * w) / 3, (row * h) / 3]);
    }
  }
  return points;
}

function renderProgress(state, page) {
  const running = page.status === "running";
  progress.hidden = !running;
  if (!running) return;
  const value = Math.max(0, Math.min(100, Math.round(page.progress || 0)));
  const stageName = stageLabel(page.stage) || "Обработка";
  progressText.textContent = `${stageName} · ${value} %`;
  const barNode = progress.querySelector("progress");
  barNode.value = value;
  barNode.textContent = `${value} %`;
}

function renderSteps(state, page) {
  const names = [
    ["detect", "Детекция"],
    ["ocr", "OCR"],
    ["translate", "Перевод"],
    ["segment", "Маска"],
    ["inpaint", "Очистка"],
    ["typeset", "Вёрстка"],
  ];
  const finished = page.status === "done" || page.status === "edited" || page.status === "offline";
  const currentIndex = names.findIndex((item) => item[0] === String(page.stage || "").toLowerCase());
  steps.innerHTML = names.map((item, index) => {
    let cls = "";
    if (finished || (page.status === "running" && currentIndex > index)) cls = "is-done";
    if (page.status === "running" && index === currentIndex) cls = "is-current";
    const mark = cls === "is-done" ? icon("check") : (cls === "is-current" ? icon("play") : "");
    const current = cls === "is-current" ? ' aria-current="step"' : "";
    return `<li class="${cls}"${current}>${mark}${item[1]}</li>`;
  }).join("");
}

function icon(id) {
  return `<svg class="icon" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

function onPointerDown(event) {
  if (stage.hidden) return;
  if (event.button !== 0 && event.button !== 1 && event.button !== 2) return;
  const pan = event.button === 1 || spaceDown || isSpaceDown() || getState().tool === "hand";
  if (pan && event.button !== 2) {
    event.preventDefault();
    drag = {
      kind: "pan",
      x: event.clientX,
      y: event.clientY,
      left: stage.scrollLeft,
      top: stage.scrollTop,
    };
    stage.classList.add("is-panning");
    stage.classList.remove("is-pan");
    frame.setPointerCapture(event.pointerId);
    return;
  }
  const state = getState();
  const point = imagePoint(event);
  if (!point) return;
  if (state.tool === "brush") {
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    drag = {
      kind: "stroke",
      mode: brushModeFromButton(event.button),
      points: [point],
    };
    drawStroke();
    frame.setPointerCapture(event.pointerId);
    return;
  }
  if (state.tool === "polyline") {
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    const mode = polylineModeFromButton(event.button);
    if (!polyDraft) polyDraft = { points: [], hover: null, mode };
    else if (!polyDraft.points.length) polyDraft.mode = mode;
    const last = polyDraft.points[polyDraft.points.length - 1];
    if (!last || Math.abs(last[0] - point[0]) >= 1 || Math.abs(last[1] - point[1]) >= 1) {
      polyDraft.points.push(point);
    }
    polyDraft.hover = null;
    drawPolylineDraft();
    return;
  }
  if (event.button === 2) {
    event.preventDefault();
    return;
  }
  if (state.tool === "region") {
    drag = { kind: "draft", x: point[0], y: point[1], point };
    frame.setPointerCapture(event.pointerId);
    return;
  }
  const styleNode = styleHandle(event);
  if (styleNode && state.tool === "select" && state.showBoxes) {
    const region = findRegion(state.document, state.selectedRegionId);
    const point = imagePoint(event);
    if (region && point) {
      if (styleNode.dataset.styleHandle === "point") {
        lastWarpPointer = {
          regionId: region.id,
          index: Number(styleNode.dataset.index),
          clientX: event.clientX,
          clientY: event.clientY,
          at: performance.now(),
        };
      }
      if (styleNode.dataset.styleHandle === "point" && event.detail >= 2) {
        resetWarpPoint(region, Number(styleNode.dataset.index));
        lastWarpPointer = null;
        event.preventDefault();
        return;
      }
      if (styleNode.dataset.styleHandle === "point" && (event.ctrlKey || event.metaKey)
        && region.style?.warp?.kind === "mesh" && Number(region.style.warp.version) >= 2) {
        toggleWarpNodeSelection(region, Number(styleNode.dataset.index));
        renderBoxes(state);
        event.preventDefault();
        return;
      }
      beginStyleDrag(styleNode, region, point);
      frame.setPointerCapture(event.pointerId);
      return;
    }
  }
  const hit = state.showBoxes ? hitTest(event) : null;
  if (hit) {
    selectRegion(hit.region.id);
    if (sameId(state.textMoveRegionId, hit.region.id)) {
      const bbox = hit.region.bbox;
      const anchorBox = hit.region.bubble_bbox || bbox;
      const anchor = Array.isArray(hit.region.text_position) && hit.region.text_position.length === 2
        ? hit.region.text_position.map(Number)
        : [anchorBox[0] + anchorBox[2] / 2, anchorBox[1] + anchorBox[3] / 2];
      drag = {
        kind: "text-position",
        id: hit.region.id,
        start: point,
        origin: anchor,
        final: anchor.slice(),
        moved: false,
      };
      frame.setPointerCapture(event.pointerId);
      return;
    }
    drag = {
      kind: hit.handle ? "resize" : "move",
      handle: hit.handle,
      id: hit.region.id,
      start: point,
      bbox: hit.region.bbox.slice(),
      moved: false,
      final: hit.region.bbox.slice(),
    };
    frame.setPointerCapture(event.pointerId);
    return;
  }
  if (state.view === "compare") {
    drag = { kind: "curtain", moved: false };
    frame.setPointerCapture(event.pointerId);
    return;
  }
  selectRegion(null);
}

function onPointerMove(event) {
  moveCursor(event);
  if (getState().tool === "polyline" && polyDraft) {
    const point = imagePoint(event);
    polyDraft.hover = point;
    drawPolylineDraft();
  }
  if (!drag) return;
  if (drag.kind === "pan") {
    stage.scrollLeft = drag.left - (event.clientX - drag.x);
    stage.scrollTop = drag.top - (event.clientY - drag.y);
    return;
  }
  if (drag.kind === "stroke") {
    const point = imagePoint(event);
    const last = drag.points[drag.points.length - 1];
    if (point && (Math.abs(point[0] - last[0]) >= 1 || Math.abs(point[1] - last[1]) >= 1)) {
      drag.points.push(point);
      drawStroke();
    }
    return;
  }
  if (drag.kind === "draft") {
    const point = imagePoint(event);
    if (!point) return;
    const x = Math.min(drag.x, point[0]);
    const y = Math.min(drag.y, point[1]);
    const w = Math.abs(point[0] - drag.x);
    const h = Math.abs(point[1] - drag.y);
    drag.final = [x, y, w, h];
    showDraft(drag.final);
    return;
  }
  if (drag.kind === "text-position") {
    const point = imagePoint(event);
    if (!point) return;
    let dx = point[0] - drag.start[0];
    let dy = point[1] - drag.start[1];
    if (event.shiftKey && Math.abs(dx) >= Math.abs(dy)) dy = 0;
    else if (event.shiftKey) dx = 0;
    drag.final = [drag.origin[0] + dx, drag.origin[1] + dy];
    drag.moved = Math.abs(dx) >= 0.5 || Math.abs(dy) >= 0.5;
    if (previewImage && !previewImage.hidden) {
      previewImage.style.transform = `translate(${dx / natural.w * frame.clientWidth}px, ${dy / natural.h * frame.clientHeight}px)`;
    }
    return;
  }
  if (drag.kind === "curtain") {
    moveCurtain(event);
    drag.moved = true;
    return;
  }
  if (drag.kind === "rotate") {
    const point = imagePoint(event);
    if (!point) return;
    const angle = pointerAngle(point, drag.bbox);
    const rotation = drag.startRotation + (angle - drag.startAngle);
    drag.moved = true;
    editDocument((document) => {
      const region = findRegion(document, drag.id);
      if (!region) return;
      region.style = region.style && typeof region.style === "object" ? region.style : {};
      region.style.rotation = rotation;
    }, { coalesce: "rotate" });
    return;
  }
  if (drag.kind === "warp") {
    const point = imagePoint(event);
    if (!point) return;
    moveWarpPoint(point, event.shiftKey);
    return;
  }
  const point = imagePoint(event);
  if (!point) return;
  const [sx, sy, sw, sh] = drag.bbox;
  const dx = point[0] - drag.start[0];
  const dy = point[1] - drag.start[1];
  let x = sx;
  let y = sy;
  let w = sw;
  let h = sh;
  if (drag.kind === "move") {
    x += event.shiftKey && Math.abs(dy) > Math.abs(dx) ? 0 : dx;
    y += event.shiftKey && Math.abs(dx) >= Math.abs(dy) ? 0 : dy;
  } else {
    if (drag.handle.includes("e")) w = sw + dx;
    if (drag.handle.includes("s")) h = sh + dy;
    if (drag.handle.includes("w")) {
      x = sx + dx;
      w = sw - dx;
    }
    if (drag.handle.includes("n")) {
      y = sy + dy;
      h = sh - dy;
    }
  }
  drag.final = clampBox([x, y, w, h], natural.w, natural.h);
  drag.moved = true;
  moveBox(drag.id, drag.final);
  if (drag.kind === "move" && previewImage && !previewImage.hidden) {
    previewImage.style.transform = `translate(${(drag.final[0] - sx) / natural.w * frame.clientWidth}px, ${(drag.final[1] - sy) / natural.h * frame.clientHeight}px)`;
  }
}

function onPointerUp(event, cancelled = false) {
  const done = drag;
  drag = null;
  stage.classList.remove("is-panning");
  syncPanCursor();
  if (done && (done.kind === "rotate" || (done.kind === "warp" && (!done.meshV2 || cancelled || done.invalid)))) {
    renderBoxes(getState());
  }
  cursor.hidden = true;
  if (!done) return;
  if (done.kind === "warp" && done.meshV2) {
    finishMeshDraft();
    if (!cancelled && done.moved && !done.invalid) {
      editDocument((document) => {
        const region = findRegion(document, done.id);
        if (!region) return;
        const warp = { ...(region.style?.warp || {}), kind: "mesh", version: 2, mesh: done.meshPoints };
        region.style = { ...(region.style || {}), warp };
      });
    }
    return;
  }
  if (done.kind === "text-position") {
    if (!cancelled && done.moved) {
      editDocument((document) => {
        const region = findRegion(document, done.id);
        if (!region) return;
        region.text_position = done.final;
        region.edited = true;
      });
    }
    if (previewImage) previewImage.style.transform = "";
    return;
  }
  if (done.kind === "stroke" && done.points.length) {
    const mode = done.mode === "erase" ? "erase" : "paint";
    const radius = getState().brushSize || 12;
    editDocument((document) => {
      document.strokes.push({
        mode,
        radius,
        points: done.points.map((point) => [Math.round(point[0]), Math.round(point[1])]),
      });
    }, { deferApply: true });
    strokeLayer.innerHTML = "";
  }
  if (done.kind === "draft") {
    clearDraft();
    const box = done.final ? clampBox(done.final, natural.w, natural.h) : null;
    if (box && box[2] >= 4 && box[3] >= 4) {
      let created = 0;
      editDocument((document) => {
        created = nextRegionId(document);
        const region = blankRegion(created, box);
        region.order = document.regions.length;
        document.regions.push(region);
      });
      if (!getState().showBoxes) patch({ showBoxes: true });
      selectRegion(created);
    }
  }
  if ((done.kind === "move" || done.kind === "resize") && done.moved) {
    if (previewImage) previewImage.style.transform = "";
    editDocument((document) => {
      const region = document.regions.find((item) => sameId(item.id, done.id));
      if (!region) return;
      region.bbox = done.final;
      region.edited = true;
    });
  }
  if (done.kind === "curtain") {
    if (!done.moved) selectRegion(null);
    else patch({ curtain: readCurtain(event) });
  }
  rememberCenter();
}

function cancelTextPositionDrag() {
  if (!drag || drag.kind !== "text-position") return;
  drag = null;
  if (previewImage) previewImage.style.transform = "";
  renderBoxes(getState());
}

function moveCurtain(event) {
  const ratio = readCurtain(event);
  curtain.style.width = `${ratio * 100}%`;
  bar.style.left = `${ratio * 100}%`;
}

function readCurtain(event) {
  const rect = frame.getBoundingClientRect();
  if (!rect.width) return getState().curtain;
  return Math.min(0.98, Math.max(0.02, (event.clientX - rect.left) / rect.width));
}

function styleHandle(event) {
  const node = event.target && event.target.closest ? event.target.closest("[data-style-handle]") : null;
  if (!node || !boxes || !boxes.contains(node)) return null;
  return node;
}

function beginStyleDrag(node, region, point) {
  const handle = node.dataset.styleHandle;
  if (handle === "rotate") {
    drag = {
      kind: "rotate",
      id: region.id,
      bbox: region.bbox.slice(),
      startAngle: pointerAngle(point, region.bbox),
      startRotation: Number(region.style && region.style.rotation) || 0,
      moved: false,
    };
    return;
  }
  const meshV2 = Boolean(region.style?.warp?.kind === "mesh" && Number(region.style.warp.version) >= 2);
  const meshPoints = Array.isArray(region.style?.warp?.mesh)
    ? region.style.warp.mesh.map((item) => [Number(item[0]), Number(item[1])])
    : defaultMesh(region.bbox[2], region.bbox[3]);
  const index = Number(node.dataset.index);
  const selectedIndices = meshV2 && sameId(selectedWarpRegionId, region.id)
    && selectedWarpNodes.size > 1 && selectedWarpNodes.has(index)
    ? [...selectedWarpNodes]
    : [index];
  selectedWarpRegionId = region.id;
  selectedWarpNodes = new Set(selectedIndices);
  drag = {
    kind: "warp",
    id: region.id,
    index,
    bbox: region.bbox.slice(),
    warpBase: region.style && region.style.warp && typeof region.style.warp === "object"
      ? structuredClone(region.style.warp)
      : { kind: "none", bend: 0, quad: null, mesh: null },
    meshV2,
    meshBasePoints: meshPoints.map((item) => item.slice()),
    meshPoints,
    selectedIndices,
    start: point.slice(),
    moved: false,
  };
}

function toggleWarpNodeSelection(region, index) {
  if (index < 0 || index >= 16) return;
  if (!sameId(selectedWarpRegionId, region.id)) {
    selectedWarpRegionId = region.id;
    selectedWarpNodes = new Set();
  }
  if (selectedWarpNodes.has(index)) selectedWarpNodes.delete(index);
  else selectedWarpNodes.add(index);
}

function pointerAngle(point, bbox) {
  const cx = bbox[0] + bbox[2] / 2;
  const cy = bbox[1] + bbox[3] / 2;
  return -Math.atan2(point[1] - cy, point[0] - cx) * (180 / Math.PI);
}

function moveWarpPoint(point, symmetric) {
  if (!drag || drag.kind !== "warp") return;
  const [bx, by, bw, bh] = drag.bbox;
  const local = [point[0] - bx, point[1] - by];
  const current = findRegion(getState().document, drag.id);
  if (!current) return;
  const oldWarp = current.style && current.style.warp && typeof current.style.warp === "object"
    ? current.style.warp
    : { kind: "none", bend: 0, quad: null, mesh: null };
  const mesh = oldWarp.kind === "mesh";
  const key = mesh ? "mesh" : "quad";
  const count = mesh ? 16 : 4;
  let deltaX = 0;
  let deltaY = 0;
  let points = Array.isArray(oldWarp[key])
    ? oldWarp[key].map((item) => [Number(item[0]) || 0, Number(item[1]) || 0])
    : (mesh ? defaultMesh(bw, bh) : defaultQuad(bw, bh));
  const index = drag.index;
  if (index < 0 || index >= Math.min(count, points.length)) return;
  if (drag.meshV2) {
    deltaX = point[0] - drag.start[0];
    deltaY = point[1] - drag.start[1];
    points = drag.meshBasePoints.map((item) => item.slice());
    const indices = drag.selectedIndices.length ? drag.selectedIndices : [index];
    for (const selectedIndex of indices) {
      points[selectedIndex] = [drag.meshBasePoints[selectedIndex][0] + deltaX, drag.meshBasePoints[selectedIndex][1] + deltaY];
    }
    if (symmetric && indices.length === 1) {
      const opposite = meshOpposite(index);
      points[opposite] = [bw - points[index][0], bh - points[index][1]];
    }
  } else {
    points[index] = local;
  }
  if (symmetric && !drag.meshV2) {
    const opposite = mesh ? meshOpposite(index) : (index + 2) % 4;
    points[opposite] = [bw - local[0], bh - local[1]];
  }
  if (mesh && !isValidMesh(points)) {
    if (!drag.invalid) {
      document.dispatchEvent(new CustomEvent("ilt-banner", {
        detail: { id: "mesh-invalid", text: "Узел создаёт вырожденную ячейку. Верните его в допустимую область." },
      }));
    }
    drag.invalid = true;
    return;
  }
  drag.invalid = false;
  if (drag.meshV2) {
    drag.meshPoints = points;
    drag.moved = Math.abs(deltaX) >= 0.5 || Math.abs(deltaY) >= 0.5;
    for (let nodeIndex = 0; nodeIndex < points.length; nodeIndex += 1) {
      placeWarpNode(drag.id, nodeIndex, points[nodeIndex], bw, bh);
    }
    const grid = boxes.querySelector(`[data-box-id="${cssEscape(drag.id)}"] .box__grid`);
    if (grid) grid.innerHTML = warpLines(points, "mesh");
    const previewRegion = findRegion(getState().document, drag.id);
    if (previewRegion) drawMeshDraft(previewRegion, points);
    return;
  }
  editDocument((document) => {
    const region = findRegion(document, drag.id);
    if (!region) return;
    const warp = { ...oldWarp };
    warp[key] = points;
    region.style = { ...(region.style || {}), warp };
  }, { coalesce: "warp" });
  drag.moved = true;
  placeWarpNode(drag.id, drag.index, local, bw, bh);
  if (symmetric) {
    const opposite = (regionWarpKind(drag.id) === "mesh") ? meshOpposite(drag.index) : (drag.index + 2) % 4;
    placeWarpNode(drag.id, opposite, [bw - local[0], bh - local[1]], bw, bh);
  }
  const region = findRegion(getState().document, drag.id);
  const grid = boxes.querySelector(`[data-box-id="${cssEscape(drag.id)}"] .box__grid`);
  if (grid && region) {
    const warp = region.style.warp;
    grid.innerHTML = warpLines(warp.kind === "mesh" ? warp.mesh : warp.quad, warp.kind);
  }
}

function regionWarpKind(id) {
  const region = findRegion(getState().document, id);
  return region && region.style && region.style.warp ? region.style.warp.kind : "";
}

function meshOpposite(index) {
  const row = Math.floor(index / 4);
  const col = index % 4;
  return (3 - row) * 4 + (3 - col);
}

function placeWarpNode(id, index, local, bw, bh) {
  const node = boxes.querySelector(`[data-box-id="${cssEscape(id)}"] [data-index="${index}"]`);
  if (!node) return;
  node.style.left = `${bw ? (local[0] / bw) * 100 : 0}%`;
  node.style.top = `${bh ? (local[1] / bh) * 100 : 0}%`;
}

function onDoubleClick(event) {
  if (getState().tool === "polyline" && polyDraft) {
    event.preventDefault();
    // Второй клик dblclick уже добавил вершину — убрать дубликат рядом с предыдущей.
    if (polyDraft.points.length >= 2) {
      const last = polyDraft.points[polyDraft.points.length - 1];
      const prev = polyDraft.points[polyDraft.points.length - 2];
      if (Math.abs(last[0] - prev[0]) < 2 && Math.abs(last[1] - prev[1]) < 2) {
        polyDraft.points.pop();
      }
    }
    commitPolylineDraft();
    return;
  }
  const node = styleHandle(event);
  if (node && node.dataset.styleHandle !== "point") return;
  const recent = lastWarpPointer
    && performance.now() - lastWarpPointer.at < 700
    && Math.hypot(event.clientX - lastWarpPointer.clientX, event.clientY - lastWarpPointer.clientY) < 14
    ? lastWarpPointer
    : null;
  if (!node && !recent) return;
  event.preventDefault();
  const candidate = node
    ? { regionId: getState().selectedRegionId, index: Number(node.dataset.index) }
    : recent;
  lastWarpPointer = null;
  const region = findRegion(getState().document, candidate.regionId);
  if (!region) return;
  resetWarpPoint(region, candidate.index);
}

function resetWarpPoint(region, index) {
  drag = null;
  const [, , bw, bh] = region.bbox;
  const mesh = region.style && region.style.warp && region.style.warp.kind === "mesh";
  const defaults = mesh ? defaultMesh(bw, bh) : defaultQuad(bw, bh);
  if (index < 0 || index >= defaults.length) return;
  editDocument((document) => {
    const current = findRegion(document, region.id);
    if (!current) return;
    const warp = current.style && current.style.warp && typeof current.style.warp === "object"
      ? { ...current.style.warp }
      : { kind: mesh ? "mesh" : "perspective", bend: 0, quad: null, mesh: null };
    const key = mesh ? "mesh" : "quad";
    const count = mesh ? 16 : 4;
    let points = Array.isArray(warp[key]) ? warp[key].map((item) => [Number(item[0]) || 0, Number(item[1]) || 0]) : null;
    if (!points || points.length !== count) points = defaults.map((item) => item.slice());
    points[index] = defaults[index].slice();
    warp[key] = points;
    current.style = { ...(current.style || {}), warp };
  });
}

function imagePoint(event) {
  const rect = frame.getBoundingClientRect();
  if (!rect.width || !rect.height || !natural.w || !natural.h) return null;
  return [
    (event.clientX - rect.left) / rect.width * natural.w,
    (event.clientY - rect.top) / rect.height * natural.h,
  ];
}

function hitTest(event) {
  const regions = [...(getState().document?.regions || [])].reverse();
  for (const region of regions) {
    const rect = screenRect(region.bbox);
    const x = event.clientX;
    const y = event.clientY;
    const margin = 8;
    const inside = x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
    const near = x >= rect.left - margin && x <= rect.right + margin && y >= rect.top - margin && y <= rect.bottom + margin;
    if (!inside && !near) continue;
    let handle = "";
    if (sameId(region.id, getState().selectedRegionId)) {
      if (Math.abs(y - rect.top) <= margin) handle += "n";
      if (Math.abs(y - rect.bottom) <= margin) handle += "s";
      if (Math.abs(x - rect.left) <= margin) handle += "w";
      if (Math.abs(x - rect.right) <= margin) handle += "e";
      if (handle === "ns" || handle === "we" || handle.length > 2) handle = "";
    }
    if (inside || handle) return { region, handle };
  }
  return null;
}

function screenRect(bbox) {
  const rect = frame.getBoundingClientRect();
  const [x, y, w, h] = bbox;
  const left = rect.left + (x / natural.w) * rect.width;
  const top = rect.top + (y / natural.h) * rect.height;
  return {
    left,
    top,
    right: left + (w / natural.w) * rect.width,
    bottom: top + (h / natural.h) * rect.height,
  };
}

function moveBox(id, bbox) {
  const node = boxes.querySelector(`[data-box-id="${cssEscape(id)}"]`);
  if (!node) return;
  const [x, y, w, h] = bbox;
  node.style.left = pct(x, natural.w);
  node.style.top = pct(y, natural.h);
  node.style.width = pct(w, natural.w);
  node.style.height = pct(h, natural.h);
}

function showDraft(bbox) {
  let node = boxes.querySelector("[data-draft]");
  if (!node) {
    boxes.hidden = false;
    node = document.createElement("div");
    node.className = "box box--draft";
    node.dataset.draft = "1";
    boxes.appendChild(node);
  }
  const [x, y, w, h] = bbox;
  node.style.left = pct(x, natural.w);
  node.style.top = pct(y, natural.h);
  node.style.width = pct(w, natural.w);
  node.style.height = pct(h, natural.h);
}

function clearDraft() {
  boxes.querySelector("[data-draft]")?.remove();
}

function drawStroke() {
  if (!drag || drag.kind !== "stroke" || !natural.w) return;
  strokeLayer.setAttribute("viewBox", `0 0 ${natural.w} ${natural.h}`);
  const points = drag.points.map((point) => `${Math.round(point[0])},${Math.round(point[1])}`).join(" ");
  const width = Math.max(1, getState().brushSize || 12) * 2;
  const color = drag.mode === "erase" ? MASK_ERASE_COLOR : MASK_PAINT_COLOR;
  strokeLayer.innerHTML = `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"></polyline>`;
}

function drawPolylineDraft() {
  if (!polyDraft || !natural.w || !strokeLayer) return;
  const points = polyDraft.points.slice();
  if (polyDraft.hover) points.push(polyDraft.hover);
  if (!points.length) {
    strokeLayer.innerHTML = "";
    return;
  }
  strokeLayer.setAttribute("viewBox", `0 0 ${natural.w} ${natural.h}`);
  const joined = points.map((point) => `${Math.round(point[0])},${Math.round(point[1])}`).join(" ");
  const color = polyDraft.mode === "erase_fill" ? MASK_ERASE_COLOR : MASK_PAINT_COLOR;
  const dots = polyDraft.points.map((point) => (
    `<circle cx="${Math.round(point[0])}" cy="${Math.round(point[1])}" r="3" fill="${color}" opacity="0.85"></circle>`
  )).join("");
  let shape = "";
  if (points.length >= 3) {
    shape = `<polygon points="${joined}" fill="${color}" fill-opacity="0.28" stroke="${color}" stroke-width="2" stroke-linejoin="round" opacity="0.9"></polygon>`;
  } else if (points.length >= 2) {
    shape = `<polyline points="${joined}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.7"></polyline>`;
  }
  strokeLayer.innerHTML = `${shape}${dots}`;
}

function moveCursor(event) {
  const tool = getState().tool;
  const erasing = drag && drag.kind === "stroke" && drag.mode === "erase";
  if ((!BRUSH_SIZE_TOOLS.has(tool) && !erasing) || !natural.w) {
    cursor.hidden = true;
    return;
  }
  const rect = frame.getBoundingClientRect();
  const diameter = Math.max(4, (getState().brushSize || 12) * 2 * (rect.width / natural.w));
  cursor.hidden = false;
  cursor.style.width = `${diameter}px`;
  cursor.style.height = `${diameter}px`;
  cursor.style.left = `${event.clientX - rect.left}px`;
  cursor.style.top = `${event.clientY - rect.top}px`;
}

function rememberCenter() {
  /* Центр видимой области читается в момент добавления региона. */
}

function pct(value, total) {
  if (!total) return "0%";
  return `${(value / total) * 100}%`;
}

function escapeAttr(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(String(value));
  return String(value);
}
