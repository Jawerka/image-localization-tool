// Кнопка «Перевести» на крупных изображениях страницы.
(() => {
  "use strict";

  if (globalThis.__iltContent) return;
  globalThis.__iltContent = true;

  const ext = globalThis.chrome ?? globalThis.browser;
  if (!ext || !ext.runtime || !ext.storage || !ext.storage.local) return;

  const DEFAULT_MIN_SIDE = 180;
  const DEFAULT_SERVER = "http://127.0.0.1:8765";
  const POLL_MS = 600;
  const SETTING_KEYS = ["serverUrl", "token", "sourceLang", "targetLang", "autoSites"];

  const records = new WeakMap();
  const jobs = new WeakMap();
  const translated = new Set();

  let settingsCache = normalizeSettings(null);
  let settingsReady = false;
  let altHeld = false;
  let autoLock = false;
  let autoAgain = false;
  let autoTimer = 0;

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
      sourceLang: typeof src.sourceLang === "string" && src.sourceLang.trim() ? src.sourceLang.trim() : "en",
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
    if (!img.complete || longerSide(img) <= DEFAULT_MIN_SIDE) return false;
    return true;
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

  function canHostOnParent(parent, img) {
    if (!parent || parent.nodeType !== 1) return false;
    const pos = getComputedStyle(parent).position;
    if (pos !== "relative" && pos !== "absolute" && pos !== "fixed") return false;
    const parentRect = parent.getBoundingClientRect();
    const imageRect = img.getBoundingClientRect();
    if (parentRect.width <= 0 || parentRect.height <= 0) return false;
    if (imageRect.width <= 0 || imageRect.height <= 0) return false;
    return parentRect.width * parentRect.height < imageRect.width * imageRect.height * 4;
  }

  function wrapperDisplay(img) {
    const display = getComputedStyle(img).display;
    if (display === "block" || display === "flex" || display === "grid") return "block";
    return "inline-block";
  }

  function createWrapper(img) {
    const displayName = wrapperDisplay(img);
    const host = document.createElement("span");
    host.className = "ilt-host";
    host.style.display = displayName;
    host.style.maxWidth = "100%";
    if (displayName === "inline-block") host.style.verticalAlign = "bottom";
    img.parentNode.insertBefore(host, img);
    host.appendChild(img);
    return host;
  }

  function placeUi(img) {
    const rec = records.get(img);
    if (!rec) return;
    const host = rec.host;
    const imgRect = img.getBoundingClientRect();
    const hostRect = host.getBoundingClientRect();
    if (rec.wrapped && Math.abs(hostRect.right - imgRect.right) < 1 && Math.abs(imgRect.top - hostRect.top) < 1) {
      rec.ui.style.top = "4px";
      rec.ui.style.right = "4px";
      return;
    }
    const style = getComputedStyle(host);
    const borderTop = parseFloat(style.borderTopWidth) || 0;
    const borderRight = parseFloat(style.borderRightWidth) || 0;
    const top = imgRect.top - hostRect.top - borderTop + 4;
    const right = hostRect.right - imgRect.right - borderRight + 4;
    rec.ui.style.top = Math.round(top) + "px";
    rec.ui.style.right = Math.round(right) + "px";
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
    if (phase === "done") rec.btn.textContent = "Заново";
    else if (phase === "idle" || phase === "error") rec.btn.textContent = "Перевести";
    if (phase === "busy") {
      rec.btn.title = "";
      placeUi(img);
    }
  }

  const STAGE_LABELS = {
    load: "Загрузка",
    queued: "Очередь",
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
    cache: "Кэш",
    done: "Готово",
  };

  function stageLabel(stage) {
    if (!stage) return "";
    const key = String(stage).toLowerCase();
    return STAGE_LABELS[key] || "";
  }

  function progressCaption(res) {
    const stage = res && typeof res.stage === "string" ? res.stage.trim() : "";
    const label = stageLabel(stage);
    const progress = res && typeof res.progress === "number" ? res.progress : null;
    const hasProgress = progress != null && Number.isFinite(progress);
    const percent = hasProgress ? Math.max(0, Math.min(100, Math.round(progress))) : null;
    if (label && percent != null) return label + " " + percent + "%";
    if (label) return label;
    if (percent != null) return percent + "%";
    return "перевод…";
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
      rec.ui.classList.add("ilt-hover");
      placeUi(img);
    };
    const leave = (event) => {
      const next = event.relatedTarget;
      if (next instanceof Node && (next === img || next === rec.ui || rec.ui.contains(next))) return;
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
    const parentEl = img.parentElement;
    let host;
    let wrapped = false;
    if (parentEl && canHostOnParent(parentEl, img)) {
      host = parentEl;
    } else {
      host = createWrapper(img);
      wrapped = true;
    }

    const ui = el("div", "ilt-ui ilt-idle");
    const btn = el("button", "ilt-btn");
    btn.type = "button";
    btn.textContent = "Перевести";
    const overlay = el("div", "ilt-overlay");
    const stage = el("span", "ilt-stage");
    const queue = el("span", "ilt-queue");
    overlay.append(stage, queue);
    const badge = el("button", "ilt-badge");
    badge.type = "button";
    badge.textContent = "Перевод";
    badge.title = "Показать оригинал";
    ui.append(btn, overlay, badge);
    host.appendChild(ui);

    const rec = { ui, btn, overlay, stage, queue, badge, host, wrapped };
    records.set(img, rec);
    img.dataset.iltPhase = "idle";
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
    if (img.dataset.iltBound === "1") return;
    if (!img.isConnected || isForeignBlob(img) || !hasAddress(img)) return;
    if (!img.complete) {
      waitLoad(img);
      return;
    }
    if (longerSide(img) <= DEFAULT_MIN_SIDE) return;
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
    const observer = new MutationObserver((mutations) => {
      for (let i = 0; i < mutations.length; i++) {
        const mutation = mutations[i];
        if (mutation.type === "attributes") {
          if (mutation.target instanceof HTMLImageElement) consider(mutation.target);
          continue;
        }
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
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "srcset"],
    });
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
      return;
    }
    ensureOriginalSaved(img, imageUrl);
    setPhase(img, "busy");
    showProgress(img, { stage: "", position: 0 });

    const page = pageUrl();
    const payload = {
      imageUrl,
      pageUrl: page,
      sourceLang: opts.sourceLang || settingsCache.sourceLang || "en",
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
      if (!jobAlive(img, token)) return;
      showFail(img, humanError(err));
      return;
    }

    while (jobAlive(img, token)) {
      const kind = classify(res);
      if (kind === "empty") {
        showFail(img, "Нет ответа");
        return;
      }
      if (kind === "idle") {
        if (opts.allowIdleFallback && !fallbackUsed) {
          fallbackUsed = true;
          idleStreak = 0;
          try {
            res = await sendMessage({ type: "translate-url", ...payload });
          } catch (err) {
            if (!jobAlive(img, token)) return;
            showFail(img, humanError(err));
            return;
          }
          continue;
        }
        idleStreak += 1;
        if (idleStreak >= 8) {
          showFail(img, (res && res.error) || "Перевод не запущен");
          return;
        }
        showProgress(img, res);
        await sleep(POLL_MS);
        if (!jobAlive(img, token)) return;
        try {
          res = await sendMessage({ type: "get-status", imageUrl, pageUrl: page });
        } catch (err) {
          if (!jobAlive(img, token)) return;
          showFail(img, humanError(err));
          return;
        }
        continue;
      }
      idleStreak = 0;
      if (kind === "error") {
        showFail(img, (res && res.error) || "Ошибка перевода");
        return;
      }
      if (kind === "done") {
        if (!jobAlive(img, token)) return;
        try {
          applyResult(img, res);
        } catch (err) {
          showFail(img, humanError(err));
        }
        return;
      }
      showProgress(img, res);
      await sleep(POLL_MS);
      if (!jobAlive(img, token)) return;
      try {
        res = await sendMessage({ type: "get-status", imageUrl, pageUrl: page });
      } catch (err) {
        if (!jobAlive(img, token)) return;
        showFail(img, humanError(err));
        return;
      }
    }
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
    const sourceLang = (langs && langs.sourceLang) || settings.sourceLang || "en";
    const targetLang = (langs && langs.targetLang) || settings.targetLang || "ru";
    await watchImage(img, {
      imageUrl: imageUrl || imageKey(img),
      sourceLang,
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
      if (!isQualifying(img)) continue;
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
    const sourceLang = (message && message.sourceLang) || settings.sourceLang || "en";
    const targetLang = (message && message.targetLang) || settings.targetLang || "ru";
    try {
      const res = await sendMessage({
        type: "translate-all",
        urls,
        pageUrl: pageUrl(),
        sourceLang,
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
    for (let i = 0; i < images.length; i++) {
      void watchImage(images[i], {
        imageUrl: imageKey(images[i]),
        sourceLang,
        targetLang,
        skipEnqueue: true,
        allowIdleFallback: true,
      });
    }
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

    const sourceLang = settingsCache.sourceLang || "en";
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
        sourceLang,
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
        sourceLang,
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
        sourceLang: Object.prototype.hasOwnProperty.call(changes, "sourceLang")
          ? changes.sourceLang.newValue
          : settingsCache.sourceLang,
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
