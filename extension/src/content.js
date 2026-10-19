// Иконка перевода на содержательных изображениях страницы.
(() => {
  "use strict";

  if (globalThis.__iltContent) return;
  globalThis.__iltContent = true;

  const ext = globalThis.chrome ?? globalThis.browser;
  if (!ext || !ext.runtime || !ext.storage || !ext.storage.local) return;

  const DEFAULT_MIN_SIDE = 180;
  const MIN_SCREEN_LONG = 160;
  const MIN_SCREEN_SHORT = 80;
  const HERO_LONG = 400;
  const HOVER_SHOW_MS = 2000;
  const DECOR_NAME = /icon|sprite|emoji|avatar/i;
  const DEFAULT_SERVER = "http://127.0.0.1:8765";
  const POLL_MS = 600;
  const SETTING_KEYS = ["serverUrl", "token", "targetLang", "autoSites"];

  const records = new WeakMap();
  const activeRecords = new Set();
  const jobs = new WeakMap();
  const translated = new Set();

  let settingsCache = normalizeSettings(null);
  let settingsReady = false;
  let altHeld = false;
  let autoLock = false;
  let autoAgain = false;
  let autoTimer = 0;
  let layoutFrame = 0;
  let motionFrame = 0;
  let motionTimer = 0;
  let resizeObserver = null;

  // Один вызов API: thenable — его результат, иначе колбэк и lastError.
  function invoke(call) {
    return new Promise((resolve, reject) => {
      const state = { settled: false, preferPromise: false, returned: undefined };
      const ok = (value) => {
        if (state.settled) return;
        state.settled = true;
        resolve(value);
      };
      const bad = (err) => {
        if (state.settled) return;
        state.settled = true;
        reject(toError(err));
      };
      try {
        state.returned = call((value) => {
          const last = ext.runtime && ext.runtime.lastError;
          queueMicrotask(() => {
            if (state.preferPromise) return;
            if (last) bad(last);
            else ok(value);
          });
        });
      } catch (err) {
        bad(err);
        return;
      }
      if (state.returned && typeof state.returned.then === "function") {
        state.preferPromise = true;
        state.returned.then(ok, bad);
      }
    });
  }

  function toError(err) {
    if (err instanceof Error) return err;
    const message = err && err.message ? String(err.message) : "Ошибка расширения";
    return new Error(message);
  }

  function humanError(err) {
    const message = err && err.message ? String(err.message) : "";
    if (/receiving end does not exist/i.test(message)) return "Фон расширения недоступен";
    if (/extension context invalidated/i.test(message)) return "Расширение перезагружено";
    return message || "Ошибка перевода";
  }

  function sendMessage(message) {
    return invoke((callback) => ext.runtime.sendMessage(message, callback));
  }

  function storageGet(keys) {
    return invoke((callback) => ext.storage.local.get(keys, callback));
  }

  function storageSet(items) {
    return invoke((callback) => ext.storage.local.set(items, callback));
  }

  function permissionsRequest(details) {
    return invoke((callback) => ext.permissions.request(details, callback));
  }

  function permissionsContains(details) {
    return invoke((callback) => ext.permissions.contains(details, callback));
  }

  function normalizeSettings(raw) {
    const src = raw && typeof raw === "object" ? raw : {};
    const auto = src.autoSites && typeof src.autoSites === "object" ? src.autoSites : {};
    return {
      serverUrl: typeof src.serverUrl === "string" && src.serverUrl.trim() ? src.serverUrl.trim() : DEFAULT_SERVER,
      token: typeof src.token === "string" ? src.token : "",
      targetLang: typeof src.targetLang === "string" && src.targetLang.trim() ? src.targetLang.trim() : "ru",
      autoSites: auto,
    };
  }

  function autoEnabled() {
    return !!(settingsCache.autoSites && settingsCache.autoSites[location.hostname] === true);
  }

  function pageUrl() {
    const href = location.href;
    const cut = href.indexOf("#");
    return cut === -1 ? href : href.slice(0, cut);
  }

  function absoluteFrom(raw) {
    if (!raw) return "";
    try {
      return new URL(raw, location.href).href;
    } catch {
      return "";
    }
  }

  function absoluteUrl(img) {
    return absoluteFrom(img.currentSrc || img.src);
  }

  function imageKey(img) {
    if (img.dataset.iltOriginal) return img.dataset.iltOriginal;
    const abs = absoluteUrl(img);
    if (!abs || abs.startsWith("blob:")) return "";
    return abs;
  }

  function urlsMatch(left, right) {
    if (!left || !right) return false;
    const a = absoluteFrom(left);
    const b = absoluteFrom(right);
    if (a && b) return a === b;
    return left === right;
  }

  function originPattern(url) {
    if (!url) return "";
    try {
      const parsed = new URL(url, location.href);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return parsed.origin + "/*";
    } catch {
      return "";
    }
  }

  function uniqueList(values) {
    const out = [];
    const seen = new Set();
    for (let i = 0; i < values.length; i++) {
      const value = values[i];
      if (!value || seen.has(value)) continue;
      seen.add(value);
      out.push(value);
    }
    return out;
  }

  function originsFor(urls) {
    const list = [];
    for (let i = 0; i < urls.length; i++) {
      const pattern = originPattern(urls[i]);
      if (pattern) list.push(pattern);
    }
    const server = originPattern(settingsCache.serverUrl || DEFAULT_SERVER);
    if (server) list.push(server);
    return uniqueList(list);
  }

  // Жест пользователя: request до первого await. Нет API — идём дальше.
  function requestOrigins(origins) {
    const unique = uniqueList(origins);
    if (!ext.permissions || typeof ext.permissions.request !== "function") {
      return Promise.resolve(true);
    }
    if (!unique.length) return Promise.resolve(true);
    return permissionsRequest({ origins: unique }).catch(() => false);
  }

  function containsOrigin(origin) {
    if (!origin) return Promise.resolve(false);
    if (!ext.permissions || typeof ext.permissions.contains !== "function") {
      return Promise.resolve(false);
    }
    return permissionsContains({ origins: [origin] })
      .then((value) => value === true)
      .catch(() => false);
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function isForeignBlob(img) {
    const values = [img.currentSrc, img.src, img.getAttribute("src") || ""];
    for (let i = 0; i < values.length; i++) {
      const value = values[i];
      if (value && value.startsWith("blob:") && value !== img.dataset.iltBlob) return true;
    }
    return false;
  }

  function longerSide(img) {
    return Math.max(img.naturalWidth || 0, img.naturalHeight || 0);
  }

  function hasAddress(img) {
    return Boolean(img.currentSrc || img.getAttribute("src") || img.getAttribute("srcset"));
  }

  function isQualifying(img) {
    if (!(img instanceof HTMLImageElement) || !img.isConnected) return false;
    if (isForeignBlob(img)) return false;
    if (!hasAddress(img)) return false;
    if (!img.complete || longerSide(img) <= DEFAULT_MIN_SIDE) return false;
    return true;
  }

  // Иконки вёрстки, шапка и сжатые на экране картинки кнопку не получают.
  function isContentImage(img) {
    if (!isQualifying(img)) return false;
    const rect = img.getBoundingClientRect();
    const longSide = Math.max(rect.width, rect.height);
    const shortSide = Math.min(rect.width, rect.height);
    if (longSide < MIN_SCREEN_LONG || shortSide < MIN_SCREEN_SHORT) return false;
    if (img.getAttribute("aria-hidden") === "true") return false;
    const role = String(img.getAttribute("role") || "").toLowerCase();
    if (role === "presentation" || role === "none") return false;
    const name = [img.className, img.id, img.getAttribute("alt") || ""].join(" ");
    if (DECOR_NAME.test(name)) return false;
    if (longSide < HERO_LONG && inPageChrome(img)) return false;
    return true;
  }

  function inPageChrome(img) {
    if (img.parentElement && img.parentElement.tagName === "BUTTON") return true;
    return Boolean(
      img.closest("nav, header, footer, [role='banner'], [role='navigation'], [role='contentinfo']")
    );
  }

  function translateIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ilt-icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("fill", "none");
    group.setAttribute("stroke", "currentColor");
    group.setAttribute("stroke-width", "1.75");
    group.setAttribute("stroke-linecap", "round");
    group.setAttribute("stroke-linejoin", "round");
    const paths = [
      "M3.5 6h7",
      "M7 6c.2 3.2-1.4 5.4-3.6 6.4",
      "M4.6 9h4.2",
      "M13 19.2 15.3 12h1.2l2.3 7.2",
      "M13.8 16.6h3.6",
      "M18.2 5.2h3.2",
      "M19.8 3.6v3.2",
    ];
    for (let i = 0; i < paths.length; i++) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", paths[i]);
      group.appendChild(path);
    }
    svg.appendChild(group);
    return svg;
  }

  function buttonLabel(phase) {
    return phase === "done" ? "Перевести заново" : "Перевести";
  }

  function el(tag, className) {
    const node = document.createElement(tag);
    node.className = className;
    return node;
  }

  function stopEvent(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  function placeUi(img) {
    const rec = records.get(img);
    if (!rec) return;
    const rect = visibleImageRect(img);
    if (!rect) {
      rec.ui.hidden = true;
      return;
    }
    const layer = layerForImage(img);
    if (layer && rec.ui.parentElement !== layer) layer.appendChild(rec.ui);
    rec.layer = layer;
    rec.ui.hidden = false;
    if (!layer || layer === document.body || layer === document.documentElement) {
      rec.ui.style.position = "fixed";
      rec.ui.style.top = `${Math.round(rect.top + 4)}px`;
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      rec.ui.style.right = `${Math.max(0, Math.round(viewportWidth - rect.right + 4))}px`;
      return;
    }
    const layerRect = layer.getBoundingClientRect();
    const scaleX = layer.offsetWidth ? layerRect.width / layer.offsetWidth : 1;
    const scaleY = layer.offsetHeight ? layerRect.height / layer.offsetHeight : 1;
    const originLeft = layerRect.left + layer.clientLeft * scaleX;
    const originTop = layerRect.top + layer.clientTop * scaleY;
    rec.ui.style.position = "absolute";
    rec.ui.style.top = `${Math.round((rect.top - originTop) / scaleY + 4)}px`;
    rec.ui.style.right = `${Math.max(0, Math.round(layer.clientWidth - (rect.right - originLeft) / scaleX + 4))}px`;
  }

  function layerForImage(img) {
    const dialog = img.closest("dialog[open]");
    if (dialog) return dialog;
    const fullscreen = document.fullscreenElement;
    if (fullscreen && (fullscreen === img || fullscreen.contains(img))) return fullscreen;
    return document.body || document.documentElement;
  }

  function visibleImageRect(img) {
    const style = getComputedStyle(img);
    const outer = img.getBoundingClientRect();
    const borderLeft = parseFloat(style.borderLeftWidth) || 0;
    const borderRight = parseFloat(style.borderRightWidth) || 0;
    const borderTop = parseFloat(style.borderTopWidth) || 0;
    const borderBottom = parseFloat(style.borderBottomWidth) || 0;
    const paddingLeft = parseFloat(style.paddingLeft) || 0;
    const paddingRight = parseFloat(style.paddingRight) || 0;
    const paddingTop = parseFloat(style.paddingTop) || 0;
    const paddingBottom = parseFloat(style.paddingBottom) || 0;
    const content = {
      left: outer.left + borderLeft + paddingLeft,
      top: outer.top + borderTop + paddingTop,
      width: Math.max(0, outer.width - borderLeft - borderRight - paddingLeft - paddingRight),
      height: Math.max(0, outer.height - borderTop - borderBottom - paddingTop - paddingBottom),
    };
    if (!content.width || !content.height) return null;

    const naturalWidth = img.naturalWidth || content.width;
    const naturalHeight = img.naturalHeight || content.height;
    const containScale = Math.min(content.width / naturalWidth, content.height / naturalHeight);
    let width = content.width;
    let height = content.height;
    const fit = style.objectFit || "fill";
    if (fit === "contain" || fit === "cover" || fit === "scale-down" || fit === "none") {
      const scale = fit === "contain" ? containScale
        : fit === "cover" ? Math.max(content.width / naturalWidth, content.height / naturalHeight)
          : fit === "scale-down" ? Math.min(1, containScale) : 1;
      width = naturalWidth * scale;
      height = naturalHeight * scale;
    }
    const [xOffset, yOffset] = objectPosition(style.objectPosition || "50% 50%", content.width, width, content.height, height);
    let rect = {
      left: content.left + xOffset,
      top: content.top + yOffset,
      right: content.left + xOffset + width,
      bottom: content.top + yOffset + height,
    };
    if (fit === "cover") rect = intersectRect(rect, {
      left: content.left, top: content.top,
      right: content.left + content.width, bottom: content.top + content.height,
    });
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
    if (rect) rect = intersectRect(rect, { left: 0, top: 0, right: viewportWidth, bottom: viewportHeight });
    for (let parent = img.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent);
      if ([parentStyle.overflow, parentStyle.overflowX, parentStyle.overflowY].some((value) => value !== "visible")) {
        const clip = parent.getBoundingClientRect();
        if (rect) rect = intersectRect(rect, clip);
      }
    }
    return rect && rect.right - rect.left > 0 && rect.bottom - rect.top > 0
      ? { ...rect, width: rect.right - rect.left, height: rect.bottom - rect.top }
      : null;
  }

  function objectPosition(value, boxWidth, imageWidth, boxHeight, imageHeight) {
    const parts = String(value).trim().split(/\s+/).filter(Boolean);
    let x = parts[0] || "50%";
    let y = parts[1] || "50%";
    if (parts.length === 1 && /^(top|bottom)$/i.test(x)) {
      y = x;
      x = "50%";
    }
    return [positionOffset(x, boxWidth - imageWidth), positionOffset(y, boxHeight - imageHeight)];
  }

  function positionOffset(token, freeSpace) {
    const value = String(token).toLowerCase();
    if (value === "center") return freeSpace * 0.5;
    if (value === "left" || value === "top") return 0;
    if (value === "right" || value === "bottom") return freeSpace;
    if (value.endsWith("%")) return freeSpace * Math.min(1, Math.max(0, (parseFloat(value) || 0) / 100));
    const pixels = value.match(/^(-?[\d.]+)px$/);
    return pixels ? Number(pixels[1]) || 0 : freeSpace * 0.5;
  }

  function intersectRect(left, right) {
    const rect = {
      left: Math.max(left.left, right.left),
      top: Math.max(left.top, right.top),
      right: Math.min(left.right, right.right),
      bottom: Math.min(left.bottom, right.bottom),
    };
    return rect.right > rect.left && rect.bottom > rect.top ? rect : null;
  }

  function refreshRecord(img, rec = records.get(img)) {
    if (!rec) return;
    if (!img.isConnected) {
      cleanupRecord(img, rec);
      return;
    }
    observeAncestors(img, rec);
    placeUi(img);
  }

  function observeAncestors(img, rec) {
    if (!resizeObserver) return;
    const next = new Set();
    for (let node = img; node && node !== document.body; node = node.parentElement) next.add(node);
    for (const node of rec.observed) {
      if (!next.has(node)) resizeObserver.unobserve(node);
    }
    for (const node of next) {
      if (!rec.observed.has(node)) resizeObserver.observe(node);
    }
    rec.observed = next;
  }

  function cleanupRecord(img, rec) {
    if (rec.hoverTimer) clearTimeout(rec.hoverTimer);
    if (resizeObserver && rec.observed) {
      for (const node of rec.observed) resizeObserver.unobserve(node);
    }
    img.removeEventListener("load", scheduleLayout);
    rec.ui.remove();
    activeRecords.delete(rec);
    delete img.dataset.iltBound;
    delete img.dataset.iltPhase;
  }

  function scheduleLayout() {
    if (layoutFrame) return;
    layoutFrame = requestAnimationFrame(() => {
      layoutFrame = 0;
      for (const rec of activeRecords) refreshRecord(rec.img, rec);
    });
  }

  function refreshMotion() {
    for (const rec of activeRecords) refreshRecord(rec.img, rec);
    if (hasActiveMotion()) {
      motionFrame = requestAnimationFrame(refreshMotion);
      return;
    }
    motionFrame = 0;
  }

  function hasActiveMotion() {
    const checked = new Set();
    for (const rec of activeRecords) {
      for (let node = rec.img; node && node !== document.body; node = node.parentElement) {
        if (checked.has(node)) continue;
        checked.add(node);
        if (node.getAnimations().some((animation) => animation.playState === "running")) return true;
      }
    }
    return false;
  }

  function startMotionTracking() {
    if (!motionFrame) motionFrame = requestAnimationFrame(refreshMotion);
    clearTimeout(motionTimer);
    motionTimer = setTimeout(() => {
      if (hasActiveMotion()) {
        if (!motionFrame) motionFrame = requestAnimationFrame(refreshMotion);
      } else if (motionFrame) {
        cancelAnimationFrame(motionFrame);
        motionFrame = 0;
        scheduleLayout();
      }
    }, 120);
  }

  function pictureSources(img) {
    const picture = img.closest("picture");
    if (!picture) return [];
    const out = [];
    const children = picture.children;
    for (let i = 0; i < children.length; i++) {
      if (children[i].tagName === "SOURCE") out.push(children[i]);
    }
    return out;
  }

  function ensureOriginalSaved(img, imageUrl) {
    if (!img.dataset.iltOriginal && imageUrl && !String(imageUrl).startsWith("blob:")) {
      img.dataset.iltOriginal = imageUrl;
    }
    if (!("iltSrcset" in img.dataset)) {
      img.dataset.iltSrcset = img.getAttribute("srcset") || "";
    }
    const sources = pictureSources(img);
    for (let i = 0; i < sources.length; i++) {
      if (!("iltSrcset" in sources[i].dataset)) {
        sources[i].dataset.iltSrcset = sources[i].getAttribute("srcset") || "";
      }
    }
  }

  function setSources(img, mode) {
    const sources = pictureSources(img);
    if (mode === "original") {
      const srcset = img.dataset.iltSrcset || "";
      if (srcset) img.setAttribute("srcset", srcset);
      else img.removeAttribute("srcset");
      for (let i = 0; i < sources.length; i++) {
        const saved = sources[i].dataset.iltSrcset || "";
        if (saved) sources[i].setAttribute("srcset", saved);
        else sources[i].removeAttribute("srcset");
      }
      if (img.dataset.iltOriginal) img.src = img.dataset.iltOriginal;
      return;
    }
    const blob = img.dataset.iltBlob;
    if (!blob) return;
    img.setAttribute("srcset", blob);
    for (let i = 0; i < sources.length; i++) sources[i].setAttribute("srcset", blob);
    img.src = blob;
  }

  function paintBadge(img, mode) {
    const rec = records.get(img);
    if (!rec) return;
    if (mode === "original") {
      rec.badge.textContent = "Оригинал";
      rec.badge.title = "Показать перевод";
    } else {
      rec.badge.textContent = "Перевод";
      rec.badge.title = "Показать оригинал";
    }
  }

  function setPhase(img, phase) {
    img.dataset.iltPhase = phase;
    const rec = records.get(img);
    if (!rec) return;
    rec.ui.classList.remove("ilt-idle", "ilt-busy", "ilt-done", "ilt-error");
    rec.ui.classList.add("ilt-" + phase);
    if (phase === "done" || phase === "idle" || phase === "error") {
      const label = buttonLabel(phase);
      rec.btn.setAttribute("aria-label", label);
      if (phase !== "error") rec.btn.title = label;
    }
    if (phase === "busy") {
      rec.btn.title = "";
      placeUi(img);
    }
  }

  function progressCaption(res) {
    const progress = res && typeof res.progress === "number" ? res.progress : null;
    if (progress == null || !Number.isFinite(progress)) return "";
    const percent = Math.max(0, Math.min(100, Math.round(progress)));
    return percent + "%";
  }

  function showProgress(img, res) {
    const rec = records.get(img);
    if (!rec) return;
    rec.stage.textContent = progressCaption(res);
    const position = res && typeof res.position === "number" ? res.position : 0;
    rec.queue.textContent = position > 0 && Number.isFinite(position) ? "в очереди: " + position : "";
  }

  function showFail(img, text) {
    setPhase(img, "error");
    const rec = records.get(img);
    if (!rec) return;
    const message = text || "Ошибка перевода";
    rec.stage.textContent = message;
    rec.queue.textContent = "";
    rec.btn.title = message;
  }

  function bindHover(img, rec) {
    const enter = () => {
      if (rec.hoverTimer || rec.ui.classList.contains("ilt-hover")) return;
      rec.hoverTimer = setTimeout(() => {
        rec.hoverTimer = 0;
        rec.ui.classList.add("ilt-hover");
        placeUi(img);
      }, HOVER_SHOW_MS);
    };
    const leave = (event) => {
      const next = event.relatedTarget;
      if (next instanceof Node && (next === img || next === rec.ui || rec.ui.contains(next))) return;
      if (rec.hoverTimer) {
        clearTimeout(rec.hoverTimer);
        rec.hoverTimer = 0;
      }
      rec.ui.classList.remove("ilt-hover");
    };
    const nodes = [img, rec.btn, rec.badge, rec.overlay];
    for (let i = 0; i < nodes.length; i++) {
      nodes[i].addEventListener("mouseenter", enter);
      nodes[i].addEventListener("mouseleave", leave);
    }
  }

  function bindControl(node, onClick) {
    const stop = (event) => event.stopPropagation();
    node.addEventListener("pointerdown", stop);
    node.addEventListener("mousedown", stop);
    node.addEventListener("mouseup", stop);
    node.addEventListener("click", (event) => {
      stopEvent(event);
      onClick(event);
    });
  }

  function mount(img) {
    if (!(img instanceof HTMLImageElement)) return;
    if (img.dataset.iltBound === "1") return;
    if (!img.isConnected || !img.parentNode) return;

    img.dataset.iltBound = "1";
    const ui = el("div", "ilt-ui ilt-idle");
    const btn = el("button", "ilt-btn");
    btn.type = "button";
    btn.appendChild(translateIcon());
    btn.setAttribute("aria-label", "Перевести");
    btn.title = "Перевести";
    const overlay = el("div", "ilt-overlay");
    const stage = el("span", "ilt-stage");
    const queue = el("span", "ilt-queue");
    overlay.append(stage, queue);
    const badge = el("button", "ilt-badge");
    badge.type = "button";
    badge.textContent = "Перевод";
    badge.title = "Показать оригинал";
    ui.append(btn, overlay, badge);

    const rec = { img, ui, btn, overlay, stage, queue, badge, layer: null, observed: new Set(), hoverTimer: 0 };
    records.set(img, rec);
    activeRecords.add(rec);
    const layer = layerForImage(img);
    if (layer) layer.appendChild(ui);
    img.dataset.iltPhase = "idle";
    img.addEventListener("load", scheduleLayout);
    observeAncestors(img, rec);
    bindHover(img, rec);
    bindControl(btn, () => onButtonClick(img));
    bindControl(badge, () => onBadgeClick(img));
    placeUi(img);
  }

  function waitLoad(img) {
    if (img.dataset.iltWait === "1") return;
    img.dataset.iltWait = "1";
    const done = () => {
      img.removeEventListener("load", done);
      img.removeEventListener("error", fail);
      if (img.dataset.iltWait !== "1") return;
      delete img.dataset.iltWait;
      consider(img);
    };
    const fail = () => {
      img.removeEventListener("load", done);
      img.removeEventListener("error", fail);
      delete img.dataset.iltWait;
    };
    img.addEventListener("load", done);
    img.addEventListener("error", fail);
    if (img.complete) {
      img.removeEventListener("load", done);
      img.removeEventListener("error", fail);
      delete img.dataset.iltWait;
      if (longerSide(img) > 0) consider(img);
    }
  }

  function consider(img) {
    if (!(img instanceof HTMLImageElement)) return;
    if (img.dataset.iltBound === "1") {
      refreshRecord(img);
      return;
    }
    if (!img.isConnected || isForeignBlob(img) || !hasAddress(img)) return;
    if (!img.complete) {
      waitLoad(img);
      return;
    }
    if (!isContentImage(img)) return;
    mount(img);
    if (img.dataset.iltBound === "1" && settingsReady && autoEnabled()) scheduleAuto();
  }

  function scanTree(root) {
    if (!root) return;
    if (root instanceof HTMLImageElement) consider(root);
    if (!root.querySelectorAll) return;
    const imgs = root.querySelectorAll("img");
    for (let i = 0; i < imgs.length; i++) consider(imgs[i]);
  }

  function startObserver() {
    const root = document.documentElement || document.body;
    if (!root) return;
    if (typeof ResizeObserver === "function") resizeObserver = new ResizeObserver(scheduleLayout);
    const observer = new MutationObserver((mutations) => {
      let layoutChanged = false;
      for (let i = 0; i < mutations.length; i++) {
        const mutation = mutations[i];
        if (mutation.type === "attributes") {
          if (mutation.target instanceof HTMLImageElement) consider(mutation.target);
          layoutChanged = true;
          continue;
        }
        layoutChanged = true;
        const nodes = mutation.addedNodes;
        for (let n = 0; n < nodes.length; n++) {
          const node = nodes[n];
          if (node instanceof HTMLImageElement) consider(node);
          else if (node instanceof Element && node.querySelectorAll) {
            const imgs = node.querySelectorAll("img");
            for (let k = 0; k < imgs.length; k++) consider(imgs[k]);
          }
        }
      }
      if (layoutChanged) {
        for (const rec of activeRecords) {
          if (!rec.img.isConnected) cleanupRecord(rec.img, rec);
        }
        scheduleLayout();
      }
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "srcset", "style", "class", "open"],
    });
    window.addEventListener("scroll", scheduleLayout, true);
    window.addEventListener("resize", scheduleLayout, { passive: true });
    document.addEventListener("fullscreenchange", scheduleLayout);
    document.addEventListener("animationstart", startMotionTracking, true);
    document.addEventListener("transitionrun", startMotionTracking, true);
    document.addEventListener("animationend", startMotionTracking, true);
    document.addEventListener("animationcancel", startMotionTracking, true);
    document.addEventListener("transitionend", startMotionTracking, true);
    document.addEventListener("transitioncancel", startMotionTracking, true);
  }

  function startJob(img) {
    const token = {};
    jobs.set(img, token);
    return token;
  }

  function jobAlive(img, token) {
    return jobs.get(img) === token && img.isConnected;
  }

  function classify(res) {
    if (!res || typeof res !== "object") return "empty";
    const status = typeof res.status === "string" ? res.status : "";
    if (status === "error") return "error";
    if (status === "done") return "done";
    if (status === "idle") return "idle";
    if (res.imageBase64 && !status) return "done";
    if (res.ok === false && !status) return "error";
    return "pending";
  }

  function base64ToBlob(data, mime) {
    let clean = String(data || "").trim();
    const marker = clean.indexOf("base64,");
    if (marker !== -1) clean = clean.slice(marker + 7);
    clean = clean.replace(/\s+/g, "");
    if (!clean) throw new Error("Пустой ответ");
    let binary;
    try {
      binary = atob(clean);
    } catch {
      throw new Error("Не удалось прочитать изображение");
    }
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i) & 255;
    const type = typeof mime === "string" && /^image\/[a-z0-9.+-]+/i.test(mime)
      ? mime.split(";")[0]
      : "image/png";
    return new Blob([bytes], { type });
  }

  function applyResult(img, res) {
    if (!res || !res.imageBase64) {
      showFail(img, (res && res.error) || "Пустой ответ");
      return;
    }
    const blob = base64ToBlob(res.imageBase64, res.mime);
    const url = URL.createObjectURL(blob);
    const previous = img.dataset.iltBlob || "";
    ensureOriginalSaved(img, img.dataset.iltOriginal || imageKey(img));
    img.dataset.iltBlob = url;
    img.dataset.iltMode = "translation";
    if (altHeld) {
      img.dataset.iltAltRestore = "translation";
      setSources(img, "original");
      paintBadge(img, "original");
    } else {
      setSources(img, "translation");
      paintBadge(img, "translation");
    }
    const rec = records.get(img);
    if (rec) rec.ui.classList.add("ilt-has-blob");
    translated.add(img);
    setPhase(img, "done");
    if (previous && previous !== url) {
      try {
        URL.revokeObjectURL(previous);
      } catch {
        /* старый blob уже отозван */
      }
    }
  }

  async function watchImage(img, opts) {
    const token = startJob(img);
    const imageUrl = opts.imageUrl || imageKey(img);
    if (!imageUrl || imageUrl.startsWith("blob:")) {
      showFail(img, "Нет адреса изображения");
      return "error";
    }
    ensureOriginalSaved(img, imageUrl);
    setPhase(img, "busy");
    showProgress(img, { stage: "", position: 0 });

    const page = pageUrl();
    const payload = {
      imageUrl,
      pageUrl: page,
      targetLang: opts.targetLang || settingsCache.targetLang || "ru",
      force: opts.force === true,
    };
    let res = null;
    let fallbackUsed = false;
    let idleStreak = 0;

    try {
      res = opts.skipEnqueue
        ? await sendMessage({ type: "get-status", imageUrl, pageUrl: page })
        : await sendMessage({ type: "translate-url", ...payload });
    } catch (err) {
      if (!jobAlive(img, token)) return "aborted";
      showFail(img, humanError(err));
      return "error";
    }

    while (jobAlive(img, token)) {
      const kind = classify(res);
      if (kind === "empty") {
        showFail(img, "Нет ответа");
        return "error";
      }
      if (kind === "idle") {
        if (opts.allowIdleFallback && !fallbackUsed) {
          fallbackUsed = true;
          idleStreak = 0;
          try {
            res = await sendMessage({ type: "translate-url", ...payload });
          } catch (err) {
            if (!jobAlive(img, token)) return "aborted";
            showFail(img, humanError(err));
            return "error";
          }
          continue;
        }
        idleStreak += 1;
        if (idleStreak >= 8) {
          showFail(img, (res && res.error) || "Перевод не запущен");
          return "error";
        }
        showProgress(img, res);
        await sleep(POLL_MS);
        if (!jobAlive(img, token)) return "aborted";
        try {
          res = await sendMessage({ type: "get-status", imageUrl, pageUrl: page });
        } catch (err) {
          if (!jobAlive(img, token)) return "aborted";
          showFail(img, humanError(err));
          return "error";
        }
        continue;
      }
      idleStreak = 0;
      if (kind === "error") {
        showFail(img, (res && res.error) || "Ошибка перевода");
        return "error";
      }
      if (kind === "done") {
        if (!jobAlive(img, token)) return "aborted";
        try {
          applyResult(img, res);
        } catch (err) {
          showFail(img, humanError(err));
          return "error";
        }
        return "done";
      }
      showProgress(img, res);
      await sleep(POLL_MS);
      if (!jobAlive(img, token)) return "aborted";
      try {
        res = await sendMessage({ type: "get-status", imageUrl, pageUrl: page });
      } catch (err) {
        if (!jobAlive(img, token)) return "aborted";
        showFail(img, humanError(err));
        return "error";
      }
    }
    return "aborted";
  }

  async function playPageChime() {
    const api = globalThis.iltChime;
    let chimeId = api ? api.defaultId : "drop";
    let chimeVolume = api ? api.defaultVolume : 50;
    try {
      const data = await storageGet(["chimeId", "chimeVolume"]);
      if (data && api && api.known(data.chimeId)) chimeId = data.chimeId;
      if (data && api) chimeVolume = api.clampVolume(data.chimeVolume);
    } catch (_) {}
    if (api && chimeId === api.offId) return;
    let played = false;
    try {
      const res = await sendMessage({ type: "play-chime", chimeId, chimeVolume });
      played = !!(res && res.ok);
    } catch (_) {}
    if (played || !api) return;
    try {
      await api.play(chimeId, chimeVolume);
    } catch (_) {}
  }

  async function readSettings(settingsPromise) {
    try {
      settingsCache = normalizeSettings(await settingsPromise);
    } catch {
      /* остаётся кэш */
    }
    return settingsCache;
  }

  function onButtonClick(img) {
    const imageUrl = imageKey(img);
    const force = img.dataset.iltPhase === "done";
    const settingsPromise = storageGet(SETTING_KEYS);
    const permPromise = requestOrigins(originsFor([imageUrl]));
    setPhase(img, "busy");
    showProgress(img, { stage: "", position: 0 });
    void finishSingle(img, imageUrl, null, settingsPromise, permPromise, force);
  }

  async function finishSingle(img, imageUrl, langs, settingsPromise, permPromise, force) {
    const settings = await readSettings(settingsPromise);
    // Диалог доступа не задерживает перевод: хост мог быть выдан раньше, сервер может ответить по CORS.
    void permPromise;
    const targetLang = (langs && langs.targetLang) || settings.targetLang || "ru";
    await watchImage(img, {
      imageUrl: imageUrl || imageKey(img),
      targetLang,
      skipEnqueue: false,
      allowIdleFallback: false,
      force: force === true,
    });
  }

  function onBadgeClick(img) {
    if (!img.dataset.iltBlob) return;
    const next = img.dataset.iltMode === "original" ? "translation" : "original";
    img.dataset.iltMode = next;
    if (altHeld) delete img.dataset.iltAltRestore;
    setSources(img, next);
    paintBadge(img, next);
  }

  function collectQualifying() {
    const out = [];
    const imgs = document.images;
    for (let i = 0; i < imgs.length; i++) {
      const img = imgs[i];
      if (!isContentImage(img)) continue;
      if (img.dataset.iltBound !== "1") mount(img);
      if (img.dataset.iltBound === "1" && imageKey(img)) out.push(img);
    }
    return out;
  }

  function onTranslateAllPage(message) {
    const images = collectQualifying();
    if (!images.length) return;
    const urls = uniqueList(images.map((img) => imageKey(img)));
    const origins = originsFor(urls);
    const permPromise = requestOrigins(origins);
    for (let i = 0; i < images.length; i++) {
      setPhase(images[i], "busy");
      showProgress(images[i], { stage: "", position: 0 });
    }
    const hostPromise = sendMessage({ type: "requestHost", origins }).catch(() => false);
    const settingsPromise = storageGet(SETTING_KEYS);
    void finishAll(message, images, urls, permPromise, hostPromise, settingsPromise);
  }

  async function finishAll(message, images, urls, permPromise, hostPromise, settingsPromise) {
    const settings = await readSettings(settingsPromise);
    // Запрос прав уходит параллельно, очередь перевода от диалога не зависит.
    void permPromise;
    void hostPromise;
    const targetLang = (message && message.targetLang) || settings.targetLang || "ru";
    try {
      const res = await sendMessage({
        type: "translate-all",
        urls,
        pageUrl: pageUrl(),
        targetLang,
      });
      if (res && res.ok === false) {
        const text = res.error || "Ошибка перевода";
        for (let i = 0; i < images.length; i++) showFail(images[i], text);
        return;
      }
    } catch (err) {
      const text = humanError(err);
      for (let i = 0; i < images.length; i++) showFail(images[i], text);
      return;
    }
    const outcomes = await Promise.all(
      images.map((img) =>
        watchImage(img, {
          imageUrl: imageKey(img),
          targetLang,
          skipEnqueue: true,
          allowIdleFallback: true,
        }),
      ),
    );
    if (outcomes.some((item) => item === "done")) await playPageChime();
  }

  function findImageByUrl(imageUrl) {
    const imgs = document.getElementsByTagName("img");
    for (let i = 0; i < imgs.length; i++) {
      const img = imgs[i];
      if (urlsMatch(img.currentSrc, imageUrl)) return img;
      if (urlsMatch(img.src, imageUrl)) return img;
      if (img.dataset.iltOriginal && urlsMatch(img.dataset.iltOriginal, imageUrl)) return img;
      const attr = img.getAttribute("src");
      if (attr && urlsMatch(attr, imageUrl)) return img;
    }
    return null;
  }

  function onTranslateImage(message) {
    if (!message || !message.imageUrl) return;
    const img = findImageByUrl(message.imageUrl);
    if (!img) return;
    if (img.dataset.iltBound !== "1") mount(img);
    let explicit = absoluteFrom(message.imageUrl);
    if (!explicit || explicit.startsWith("blob:")) explicit = imageKey(img);
    if (!explicit) return;
    const settingsPromise = storageGet(SETTING_KEYS);
    const permPromise = requestOrigins(originsFor([explicit]));
    setPhase(img, "busy");
    showProgress(img, { stage: "", position: 0 });
    void finishSingle(img, explicit, null, settingsPromise, permPromise);
  }

  function eachTranslated(fn) {
    translated.forEach((img) => {
      if (!img.isConnected) {
        translated.delete(img);
        return;
      }
      if (!img.dataset.iltBlob) return;
      fn(img);
    });
  }

  function onAltDown(event) {
    if (event.key !== "Alt" || event.repeat || altHeld) return;
    altHeld = true;
    eachTranslated((img) => {
      img.dataset.iltAltRestore = img.dataset.iltMode || "translation";
      setSources(img, "original");
      paintBadge(img, "original");
    });
  }

  function onAltUp(event) {
    if (event.key !== "Alt" || !altHeld) return;
    altHeld = false;
    eachTranslated((img) => {
      const restore = img.dataset.iltAltRestore;
      if (!restore) return;
      delete img.dataset.iltAltRestore;
      const mode = restore === "original" ? "original" : "translation";
      setSources(img, mode);
      paintBadge(img, mode);
    });
  }

  function bindAlt() {
    window.addEventListener("keydown", onAltDown, true);
    window.addEventListener("keyup", onAltUp, true);
    window.addEventListener("blur", () => {
      if (!altHeld) return;
      onAltUp({ key: "Alt" });
    });
  }

  function scheduleAuto() {
    if (!settingsReady || !autoEnabled()) return;
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => {
      autoTimer = 0;
      void flushAuto();
    }, 80);
  }

  async function flushAuto() {
    if (!autoEnabled()) return;
    if (autoLock) {
      autoAgain = true;
      return;
    }
    autoLock = true;
    try {
      do {
        autoAgain = false;
        await runAutoOnce();
      } while (autoAgain && autoEnabled());
    } finally {
      autoLock = false;
    }
  }

  async function runAutoOnce() {
    const images = collectQualifying().filter((img) => {
      const phase = img.dataset.iltPhase;
      return phase !== "busy" && phase !== "done";
    });
    const allowed = [];
    const grants = new Map();
    for (let i = 0; i < images.length; i++) {
      const img = images[i];
      const origin = originPattern(imageKey(img));
      if (!origin) continue;
      let ok = grants.get(origin);
      if (ok === undefined) {
        ok = await containsOrigin(origin);
        grants.set(origin, ok);
      }
      const phase = img.dataset.iltPhase;
      if (ok && phase !== "busy" && phase !== "done") allowed.push(img);
    }
    if (!allowed.length) return;

    const targetLang = settingsCache.targetLang || "ru";
    const urls = uniqueList(allowed.map((img) => imageKey(img)));
    for (let i = 0; i < allowed.length; i++) {
      setPhase(allowed[i], "busy");
      showProgress(allowed[i], { stage: "", position: 0 });
    }
    try {
      const res = await sendMessage({
        type: "translate-all",
        urls,
        pageUrl: pageUrl(),
        targetLang,
      });
      if (res && res.ok === false) {
        const text = res.error || "Ошибка перевода";
        for (let i = 0; i < allowed.length; i++) showFail(allowed[i], text);
        return;
      }
    } catch (err) {
      const text = humanError(err);
      for (let i = 0; i < allowed.length; i++) showFail(allowed[i], text);
      return;
    }
    for (let i = 0; i < allowed.length; i++) {
      void watchImage(allowed[i], {
        imageUrl: imageKey(allowed[i]),
        targetLang,
        skipEnqueue: true,
        allowIdleFallback: true,
      });
    }
  }

  function bindStorage() {
    if (!ext.storage.onChanged) return;
    ext.storage.onChanged.addListener((changes, area) => {
      if (area !== "local" || !changes) return;
      settingsCache = normalizeSettings({
        serverUrl: Object.prototype.hasOwnProperty.call(changes, "serverUrl")
          ? changes.serverUrl.newValue
          : settingsCache.serverUrl,
        token: Object.prototype.hasOwnProperty.call(changes, "token")
          ? changes.token.newValue
          : settingsCache.token,
        targetLang: Object.prototype.hasOwnProperty.call(changes, "targetLang")
          ? changes.targetLang.newValue
          : settingsCache.targetLang,
        autoSites: Object.prototype.hasOwnProperty.call(changes, "autoSites")
          ? changes.autoSites.newValue
          : settingsCache.autoSites,
      });
      if (autoEnabled()) scheduleAuto();
    });
  }

  function bindMessages() {
    ext.runtime.onMessage.addListener((message) => {
      if (!message || typeof message.type !== "string") return;
      if (message.type === "translate-all-page") {
        onTranslateAllPage(message);
        return;
      }
      if (message.type === "translate-image") onTranslateImage(message);
    });
  }

  function init() {
    bindMessages();
    bindAlt();
    bindStorage();
    startObserver();
    const settingsPromise = storageGet(SETTING_KEYS);
    scanTree(document.documentElement || document.body);
    settingsPromise
      .then((raw) => {
        settingsCache = normalizeSettings(raw);
      })
      .catch(() => {
        /* дефолты */
      })
      .then(() => {
        settingsReady = true;
        if (autoEnabled()) scheduleAuto();
      });
  }

  // storageSet нужен тому же контракту, что get; фон сам пишет настройки.
  void storageSet;

  init();
})();
