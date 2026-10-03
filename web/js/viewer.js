/* Просмотрщик: масштаб, шторка, рамки, кисть и ластик. */

import { imageUrl } from "./api.js";
import {
  blankRegion,
  clampBox,
  editDocument,
  findRegion,
  getState,
  isReadyStatus,
  nextRegionId,
  patch,
  sameId,
  selectRegion,
  stageLabel,
  subscribe,
} from "./state.js";
import { isSpaceDown } from "./keys.js";

const TOOLS = ["select", "region", "brush", "eraser"];
const VIEWS = ["original", "result", "compare"];

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
let natural = { w: 0, h: 0 };
let drag = null;
let previewImage = null;
let previewUrl = "";
let spaceDown = false;

export function init() {
  stage = document.querySelector("[data-role='stage']");
  frame = document.querySelector("[data-role='frame']");
  baseImage = document.querySelector("[data-role='img-base']");
  curtain = document.querySelector("[data-role='curtain']");
  curtainImage = document.querySelector("[data-role='img-curtain']");
  maskImage = document.querySelector("[data-role='img-mask']");
  boxes = document.querySelector("[data-role='boxes']");
  previewImage = document.querySelector("[data-role='style-preview']");
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

  const range = document.querySelector("[data-role='brush-size']");
  range.addEventListener("input", () => {
    patch({ brushSize: Number(range.value) || 1 });
  });
  document.querySelector("[data-role='zoom-out']").addEventListener("click", () => stepZoom(-1));
  document.querySelector("[data-role='zoom-in']").addEventListener("click", () => stepZoom(1));
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
  frame.addEventListener("dblclick", onDoubleClick);
  frame.addEventListener("pointermove", onPointerMove);
  frame.addEventListener("pointerup", onPointerUp);
  frame.addEventListener("pointercancel", onPointerUp);
  frame.addEventListener("pointerleave", () => {
    cursor.hidden = true;
  });
  stage.addEventListener("wheel", onWheel, { passive: false });
  stage.addEventListener("scroll", rememberCenter);
  baseImage.addEventListener("load", onImageLoad);
  baseImage.addEventListener("error", onBaseError);
  maskImage.addEventListener("load", () => maskImage.classList.remove("is-missing"));
  maskImage.addEventListener("error", () => maskImage.classList.add("is-missing"));
  window.addEventListener("resize", layout);
  if (window.ResizeObserver) new ResizeObserver(() => layout()).observe(stage);
  subscribe(sync);
  sync(getState());
}

export function setSpace(down) {
  spaceDown = down;
  stage.classList.toggle("is-pan", down && !drag);
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
  if (mode === "fit") {
    stage.scrollLeft = 0;
    stage.scrollTop = 0;
  }
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

export function nudgeBrush(delta) {
  const next = Math.max(1, Math.min(64, (getState().brushSize || 12) + delta));
  patch({ brushSize: next });
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
  const page = state.pages.find((item) => item.id === state.activePageId);
  const enabled = Boolean(page);
  document.querySelectorAll("[data-view-control]").forEach((node) => {
    node.disabled = !enabled;
  });
  document.querySelector("[data-role='undo']").disabled = !state.undoCount;
  document.querySelector("[data-role='redo']").disabled = !state.redoCount;
  const range = document.querySelector("[data-role='brush-size']");
  if (document.activeElement !== range) range.value = String(state.brushSize);
  if (sizeLabel) sizeLabel.textContent = String(state.brushSize);

  setRadio("[data-role='view-group']", state.view);
  setRadio("[data-role='tool-group']", state.tool);
  const boxesButton = document.querySelector("[data-role='layer-boxes']");
  const maskButton = document.querySelector("[data-role='layer-mask']");
  boxesButton.setAttribute("aria-pressed", state.showBoxes ? "true" : "false");
  maskButton.setAttribute("aria-pressed", state.showMask ? "true" : "false");

  stage.hidden = !enabled;
  steps.hidden = !enabled;
  if (!enabled) return;

  const version = state.document?.version || page.version || 0;
  setSrc(baseImage, page, state.view === "original" ? "original" : "result", version);
  setSrc(curtainImage, page, "original", version);
  setSrc(maskImage, page, "mask", version);
  baseImage.alt = `${state.view === "original" ? "Оригинал" : "Результат"} страницы ${page.name}`;
  frame.classList.toggle("frame--mask", state.showMask);
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
  stage.classList.toggle("is-cross", enabled && (state.tool === "region" || state.tool === "brush" || state.tool === "eraser") && !spaceDown);
  layout();
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
  if (image === baseImage && kind === "result" && !isReadyStatus(page.status)) {
    showResultGap(true);
    return;
  }
  if (image === baseImage) showResultGap(false);
  const url = imageUrl(page.id, kind, version);
  if (image.dataset.url === url) return;
  image.dataset.url = url;
  if (image === maskImage) image.classList.remove("is-missing");
  image.src = url;
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
  if (view === "result" || view === "compare") showResultGap(true);
}

function onImageLoad() {
  natural = { w: baseImage.naturalWidth || 0, h: baseImage.naturalHeight || 0 };
  patch({ imageSize: { ...natural } });
  layout();
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
  return Number(zoom) || 1;
}

function layout() {
  if (!frame || stage.hidden || !natural.w) return;
  const scale = currentScale();
  const width = Math.max(1, Math.round(natural.w * scale));
  const height = Math.max(1, Math.round(natural.h * scale));
  if (frame.style.getPropertyValue("--frame-w") === `${width}px` && frame.style.getPropertyValue("--frame-h") === `${height}px`) {
    updateZoomLabel(scale);
    return;
  }
  frame.style.setProperty("--frame-w", `${width}px`);
  frame.style.setProperty("--frame-h", `${height}px`);
  updateZoomLabel(scale);
}

function updateZoomLabel(scale) {
  const text = getState().zoom === "fit" ? "Вписать" : `${Math.round(scale * 100)} %`;
  if (zoomLabel.textContent !== text) zoomLabel.textContent = text;
  const status = document.querySelector("[data-role='zoom-label']");
  if (status && status.textContent !== text) status.textContent = text;
}

function stepZoom(direction) {
  const steps = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
  const scale = currentScale();
  const next = direction > 0
    ? (steps.find((item) => item > scale + 0.01) || Math.min(8, scale * 1.25))
    : ([...steps].reverse().find((item) => item < scale - 0.01) || Math.max(0.1, scale / 1.25));
  patch({ zoom: next });
}

function onWheel(event) {
  if (!event.ctrlKey || stage.hidden) return;
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
  const next = Math.min(8, Math.max(0.1, currentScale() * factor));
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
  return points.map((point, index) => {
    const left = w ? (Number(point[0]) / w) * 100 : 0;
    const top = h ? (Number(point[1]) / h) * 100 : 0;
    return `<button type="button" class="box__point" data-style-handle="point" data-index="${index}" style="left:${left}%;top:${top}%" aria-label="Точка ${index + 1}"></button>`;
  }).join("");
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
  if (event.button !== 0 || stage.hidden) return;
  if (spaceDown || isSpaceDown()) {
    drag = {
      kind: "pan",
      x: event.clientX,
      y: event.clientY,
      left: stage.scrollLeft,
      top: stage.scrollTop,
    };
    stage.classList.add("is-panning");
    frame.setPointerCapture(event.pointerId);
    return;
  }
  const state = getState();
  const point = imagePoint(event);
  if (!point) return;
  if (state.tool === "brush" || state.tool === "eraser") {
    drag = { kind: "stroke", points: [point] };
    drawStroke();
    frame.setPointerCapture(event.pointerId);
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
      beginStyleDrag(styleNode, region, point);
      frame.setPointerCapture(event.pointerId);
      return;
    }
  }
  const hit = state.showBoxes ? hitTest(event) : null;
  if (hit) {
    selectRegion(hit.region.id);
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
    x += dx;
    y += dy;
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
}

function onPointerUp(event) {
  const done = drag;
  drag = null;
  stage.classList.remove("is-panning");
  if (done && (done.kind === "rotate" || done.kind === "warp")) renderBoxes(getState());
  cursor.hidden = true;
  if (!done) return;
  if (done.kind === "stroke" && done.points.length) {
    const mode = getState().tool === "eraser" ? "erase" : "paint";
    const radius = getState().brushSize || 12;
    editDocument((document) => {
      document.strokes.push({
        mode,
        radius,
        points: done.points.map((point) => [Math.round(point[0]), Math.round(point[1])]),
      });
    });
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
  drag = {
    kind: "warp",
    id: region.id,
    index: Number(node.dataset.index),
    bbox: region.bbox.slice(),
    moved: false,
  };
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
  editDocument((document) => {
    const region = findRegion(document, drag.id);
    if (!region) return;
    const warp = region.style && region.style.warp && typeof region.style.warp === "object"
      ? { ...region.style.warp }
      : { kind: "none", bend: 0, quad: null, mesh: null };
    const mesh = warp.kind === "mesh";
    const key = mesh ? "mesh" : "quad";
    const count = mesh ? 16 : 4;
    let points = Array.isArray(warp[key]) ? warp[key].map((item) => [Number(item[0]) || 0, Number(item[1]) || 0]) : null;
    if (!points || points.length !== count) points = mesh ? defaultMesh(bw, bh) : defaultQuad(bw, bh);
    const index = drag.index;
    if (index < 0 || index >= points.length) return;
    points[index] = local;
    if (symmetric) {
      const opposite = mesh ? meshOpposite(index) : (index + 2) % 4;
      points[opposite] = [bw - local[0], bh - local[1]];
    }
    warp[key] = points;
    region.style = { ...(region.style || {}), warp };
  }, { coalesce: "warp" });
  drag.moved = true;
  placeWarpNode(drag.id, drag.index, local, bw, bh);
  if (symmetric) {
    const opposite = (regionWarpKind(drag.id) === "mesh") ? meshOpposite(drag.index) : (drag.index + 2) % 4;
    placeWarpNode(drag.id, opposite, [bw - local[0], bh - local[1]], bw, bh);
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
  const node = styleHandle(event);
  if (!node || node.dataset.styleHandle !== "point") return;
  event.preventDefault();
  drag = null;
  const index = Number(node.dataset.index);
  const region = findRegion(getState().document, getState().selectedRegionId);
  if (!region) return;
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
  strokeLayer.innerHTML = `<polyline points="${points}" fill="none" stroke="#ffffff" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"></polyline>`;
}

function moveCursor(event) {
  const tool = getState().tool;
  if ((tool !== "brush" && tool !== "eraser") || !natural.w) {
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
