// Одна кнопка на картинку: покой, прогресс, готовность, ошибка, запасное наложение.
(() => {
  "use strict";
  const ext = globalThis.chrome ?? globalThis.browser;
  const model = globalThis.iltButtonModel || {
    stageLabel: (stage) => stage || "Переводим",
    formatEta: () => "",
    pickCorner: () => "tr",
  };
  const records = new Map();
  const cache = new Map();
  const pointer = { x: -1, y: -1 };
  let port = null;
  let theme = "system";
  let anchorOk = null;

  const GLYPH = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M4 5.5h9.2a1.5 1.5 0 0 1 1.5 1.5v6.2a1.5 1.5 0 0 1-1.5 1.5H8.2L6 17.2v-2.5H4a1.5 1.5 0 0 1-1.5-1.5V7A1.5 1.5 0 0 1 4 5.5Z"/><path fill="none" stroke="currentColor" stroke-width="1.6" d="M14.2 8.2h5.3v4.6h-2.2L16 14.6v-1.8h-1.8z"/></svg>`;

  window.addEventListener("pointermove", (event) => {
    if (!event.isTrusted) return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    updatePanels();
  }, { capture: true, passive: true });

  const PANEL_ZONE = 10;

  function nearBox(element, pad) {
    if (element.hidden) return false;
    const box = element.getBoundingClientRect();
    return pointer.x >= box.left - pad && pointer.x <= box.right + pad
      && pointer.y >= box.top - pad && pointer.y <= box.bottom + pad;
  }

  // Мини-панель открыта, только пока курсор у кнопки или у самой панели.
  function updatePanels() {
    for (const record of records.values()) {
      if (record.phase !== "done" || record.clipped) continue;
      if (!record.faceShown && !record.panelOpen) continue;
      const hot = nearBox(record.button, PANEL_ZONE) || (record.panelOpen && nearBox(record.panel, PANEL_ZONE));
      if (!hot && record.faceShown && !nearBox(record.node, 0)) record.faceShown = false;
      if (hot !== record.panelOpen) openPanel(record, hot);
      else if (!record.faceShown) applyFade(record);
    }
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (value, error) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(value);
      };
      let pending;
      try {
        pending = ext.runtime.sendMessage(message, (value) => {
          const error = ext.runtime.lastError;
          if (error) finish(undefined, new Error(error.message));
          else finish(value);
        });
      } catch (error) {
        finish(undefined, error);
        return;
      }
      // В Chrome 144 промис sendMessage завершается undefined, если передан callback.
      if (pending?.then) {
        pending.then(
          (value) => { if (value !== undefined) finish(value); },
          (error) => finish(undefined, error instanceof Error ? error : new Error(String(error || "Нет ответа от расширения"))),
        );
      }
    });
  }

  function log(ev, msg, data) {
    globalThis.iltLog?.write({ src: "page", ev: ev, msg: msg, data: data || {} });
  }

  function connectPort() {
    if (!ext.runtime?.connect || port) return;
    try {
      port = ext.runtime.connect({ name: "ilt-page" });
    } catch (_) {
      port = null;
      return;
    }
    port.onMessage.addListener((message) => {
      if (!message || message.type !== "job") return;
      for (const record of records.values()) {
        if (record.imageUrl === message.imageUrl && record.pageUrl === message.pageUrl) {
          record.pending = message;
          record.onUpdate?.(message);
        }
      }
    });
    port.onDisconnect.addListener(() => {
      port = null;
      setTimeout(connectPort, 400);
    });
  }

  function storageGet(defaults) {
    return new Promise((resolve) => {
      if (!ext.storage?.local) { resolve(defaults); return; }
      const response = ext.storage.local.get(defaults, (value) => resolve(value || defaults));
      if (response?.then) response.then((value) => resolve(value || defaults), () => resolve(defaults));
    });
  }

  function applyTheme(host) {
    host.dataset.theme = theme === "light" || theme === "dark" ? theme : "system";
  }

  function readTheme() {
    storageGet({ theme: "system" }).then((value) => {
      theme = value.theme === "light" || value.theme === "dark" ? value.theme : "system";
      for (const record of records.values()) applyTheme(record.host);
    }).catch(() => {});
  }

  function remove(record) {
    if (records.get(record.node) !== record) return;
    records.delete(record.node);
    record.revision += 1;
    record.observer?.disconnect();
    record.addressObserver?.disconnect();
    if (record.node instanceof HTMLImageElement) globalThis.iltNativeSwap?.restore(record.node);
    try { record.button?.hidePopover?.(); } catch (_) {}
    try { record.host.hidePopover?.(); } catch (_) {}
    record.host.remove();
    record.bitmap?.close();
    record.bitmap = null;
  }

  function absoluteUrl(value) {
    try { return new URL(value, document.baseURI).href; }
    catch (_) { return String(value || ""); }
  }

  // Атрибут src меняется раньше currentSrc. Пока подмена ещё не blob, это новая картинка.
  function watchAddress(record) {
    record.addressObserver?.disconnect();
    if (!(record.node instanceof HTMLImageElement) || typeof MutationObserver !== "function") return;
    const observer = new MutationObserver(() => {
      if (records.get(record.node) !== record || record.mode === "swap") return;
      const next = absoluteUrl(record.node.getAttribute("src") || "");
      if (!next || next.startsWith("blob:") || next === record.imageUrl) return;
      remove(record);
    });
    observer.observe(record.node, { attributes: true, attributeFilter: ["src", "srcset"] });
    record.addressObserver = observer;
  }

  function liveSource(record) {
    const swap = globalThis.iltNativeSwap;
    if (record.mode === "swap" && swap?.isSwapped(record.node)) return swap.originalUrl(record.node) || record.imageUrl;
    return record.source() || record.imageUrl;
  }

  function alive(record, revision = record.revision) {
    if (records.get(record.node) !== record || record.revision !== revision || !record.node.isConnected) return false;
    if (record.phase === "idle") return true;
    if (record.mode === "swap") return liveSource(record) === record.imageUrl;
    return record.source() === record.imageUrl && location.href === record.pageUrl;
  }

  function cornerBlocked(img, x, y, host) {
    const stack = document.elementsFromPoint(x + 16, y + 16);
    for (let i = 0; i < stack.length; i += 1) {
      const node = stack[i];
      if (!node || node === host || host.contains(node)) continue;
      if (node === img || img.contains(node)) return false;
      if (node.matches?.("a, button, [role='button'], video, input, textarea, select, summary")) return true;
    }
    return false;
  }

  function clippedAway(node) {
    const rect = node.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return true;
    if (rect.bottom < 0 || rect.right < 0 || rect.top > innerHeight || rect.left > innerWidth) return true;
    for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const css = getComputedStyle(ancestor);
      const overflow = `${css.overflow}${css.overflowX}${css.overflowY}`;
      if (!/(hidden|clip|scroll|auto)/.test(overflow)) continue;
      const bounds = ancestor.getBoundingClientRect();
      const width = Math.min(rect.right, bounds.right) - Math.max(rect.left, bounds.left);
      const height = Math.min(rect.bottom, bounds.bottom) - Math.max(rect.top, bounds.top);
      if (width < 8 || height < 8) return true;
    }
    return false;
  }

  function cornerOrigin(rect, name) {
    const size = 32;
    const gap = 6;
    if (name === "tl") return { left: rect.left + gap, top: rect.top + gap };
    if (name === "br") return { left: rect.right - size - gap, top: rect.bottom - size - gap };
    if (name === "bl") return { left: rect.left + gap, top: rect.bottom - size - gap };
    return { left: rect.right - size - gap, top: rect.top + gap };
  }

  function imageRect(node) {
    const box = node.getBoundingClientRect();
    const css = getComputedStyle(node);
    if (typeof model.visibleImageRect === "function") {
      return model.visibleImageRect(box, node.naturalWidth, node.naturalHeight, css.objectFit, css.objectPosition);
    }
    return box;
  }

  function chooseCorner(record) {
    const rect = imageRect(record.node);
    const blocked = {};
    for (const name of ["tr", "tl", "br", "bl"]) {
      const origin = cornerOrigin(rect, name);
      blocked[name] = cornerBlocked(record.node, origin.left, origin.top, record.host);
    }
    record.corner = model.pickCorner(blocked);
    record.button.dataset.corner = record.corner;
    return rect;
  }

  function useAnchor(record) {
    if (anchorOk === false) return false;
    if (!record.button.showPopover || !globalThis.CSS?.supports?.("position-anchor", "auto")) {
      anchorOk = false;
      return false;
    }
    try {
      record.button.showPopover({ source: record.node });
      record.button.classList.add("anchored");
      anchorOk = true;
      return true;
    } catch (_) {
      anchorOk = false;
      record.button.classList.remove("anchored");
      try { record.button.showPopover(); } catch (_) { /* фолбэк координатами */ }
      return false;
    }
  }

  function paintBackground(record, style) {
    const width = Math.max(1, record.node.clientWidth);
    const height = Math.max(1, record.node.clientHeight);
    const key = [width, height, style.backgroundSize, style.backgroundPosition, style.backgroundRepeat].join("|");
    if (record.backgroundKey === key) return;
    const image = record.bitmap;
    const size = style.backgroundSize.split(/\s+/);
    const length = (value, available) => (value?.endsWith("%") ? parseFloat(value) / 100 * available : parseFloat(value));
    let drawWidth = image.width;
    let drawHeight = image.height;
    if (size[0] === "cover" || size[0] === "contain") {
      const scale = Math[size[0] === "cover" ? "max" : "min"](width / image.width, height / image.height);
      drawWidth *= scale;
      drawHeight *= scale;
    } else {
      if (size[0] !== "auto") drawWidth = length(size[0], width);
      if (size[1] && size[1] !== "auto") drawHeight = length(size[1], height);
      else drawHeight = image.height * drawWidth / image.width;
      if (size[0] === "auto" && size[1] && size[1] !== "auto") drawWidth = image.width * drawHeight / image.height;
    }
    const position = style.backgroundPosition.split(/\s+/);
    const offset = (value, space) => (value?.endsWith("%") ? parseFloat(value) / 100 * space : parseFloat(value));
    const x = offset(position[0], width - drawWidth);
    const y = offset(position[1], height - drawHeight);
    if (![drawWidth, drawHeight, x, y].every(Number.isFinite) || drawWidth <= 0 || drawHeight <= 0
      || style.backgroundOrigin !== "padding-box" || style.backgroundAttachment !== "scroll") {
      throw new Error("Сложный CSS-фон: доступен оригинал");
    }
    record.canvas.width = width;
    record.canvas.height = height;
    const context = record.canvas.getContext("2d");
    const repeat = style.backgroundRepeat;
    if (!["repeat", "repeat-x", "repeat-y", "no-repeat"].includes(repeat)) throw new Error("Сложное повторение фона: доступен оригинал");
    const pattern = context.createPattern(image, repeat);
    pattern.setTransform(new DOMMatrix().translate(x, y).scale(drawWidth / image.width, drawHeight / image.height));
    context.fillStyle = pattern;
    context.fillRect(0, 0, width, height);
    record.backgroundKey = key;
  }

  function place(record) {
    if (!record.node.isConnected) { remove(record); return; }
    const parent = record.node.closest("dialog[open]") || document.fullscreenElement || document.documentElement;
    if (record.host.parentElement !== parent) {
      try { record.host.hidePopover(); } catch (_) {}
      parent.append(record.host);
      try { record.host.showPopover(); } catch (_) {}
      if (record.anchored) useAnchor(record);
    }
    const rect = chooseCorner(record);
    record.clipped = record.phase !== "idle" && record.phase !== "error" && clippedAway(record.node);
    record.button.hidden = record.clipped;
    applyFade(record);
    if (!record.anchored) {
      const origin = cornerOrigin(rect, record.corner);
      record.button.style.left = `${Math.round(origin.left)}px`;
      record.button.style.top = `${Math.round(origin.top)}px`;
    }
    if (record.phase === "idle") {
      record.frame.hidden = true;
      return;
    }
    if (!alive(record)) { remove(record); return; }
    const node = record.node;
    const style = getComputedStyle(node);
    let left = Math.max(0, rect.left);
    let top = Math.max(0, rect.top);
    let right = Math.min(innerWidth, rect.right);
    let bottom = Math.min(innerHeight, rect.bottom);
    for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const css = getComputedStyle(ancestor);
      const bounds = ancestor.getBoundingClientRect();
      if (/(hidden|clip|scroll|auto)/.test(css.overflowX)) {
        left = Math.max(left, bounds.left);
        right = Math.min(right, bounds.right);
      }
      if (/(hidden|clip|scroll|auto)/.test(css.overflowY)) {
        top = Math.max(top, bounds.top);
        bottom = Math.min(bottom, bounds.bottom);
      }
    }
    record.frame.hidden = record.mode === "swap" || record.original || !record.bitmap;
    if (record.mode !== "swap" && record.bitmap && !(node instanceof HTMLImageElement) && !(node instanceof HTMLCanvasElement)) {
      try { paintBackground(record, style); } catch (error) { record.note.textContent = error.message; }
    }
    if (record.mode !== "swap") {
      Object.assign(record.frame.style, {
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        borderRadius: style.borderRadius,
      });
    }
    const box = record.button.getBoundingClientRect();
    placeBeside(record.panel, box, record.corner);
    placeBeside(record.detail, box, record.corner);
  }

  // Готовая кнопка и мини-панель не исчезают из раскладки, а гаснут до нуля.
  function applyFade(record) {
    const done = record.phase === "done";
    const shown = !record.clipped && (!done || record.faceShown || record.panelOpen || record.showCheck);
    record.button.classList.toggle("off", !shown);
    record.panel.hidden = !done;
    record.panel.classList.toggle("off", record.clipped || !record.panelOpen);
    if (!record.panelOpen) record.menu.hidden = true;
  }

  // Панель стоит в одном ряду с кнопкой и растёт внутрь картинки, не выходя за окно.
  function placeBeside(element, box, corner) {
    if (element.hidden) return;
    const margin = 8;
    const gap = 6;
    const size = element.getBoundingClientRect();
    const right = corner === "tr" || corner === "br";
    let left = right ? box.left - gap - size.width : box.right + gap;
    let top = box.top + (box.height - size.height) / 2;
    const fits = left >= margin && left + size.width <= innerWidth - margin;
    if (!fits) {
      left = Math.min(Math.max(margin, right ? box.right - size.width : box.left), innerWidth - size.width - margin);
      top = corner === "br" || corner === "bl" ? box.top - gap - size.height : box.bottom + gap;
    }
    top = Math.min(Math.max(margin, top), innerHeight - size.height - margin);
    element.style.left = `${Math.round(Math.max(margin, left))}px`;
    element.style.top = `${Math.round(top)}px`;
  }

  function track() {
    for (const record of records.values()) place(record);
  }

  window.addEventListener("scroll", track, true);
  window.addEventListener("resize", track);

  function glyph() {
    const wrap = document.createElement("span");
    wrap.className = "glyph";
    wrap.innerHTML = GLYPH;
    return wrap;
  }

  function stop(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  function buttonFace(record) {
    const button = record.button;
    button.replaceChildren();
    button.classList.remove("bad");
    if (record.phase === "error") {
      button.classList.add("bad");
      button.setAttribute("aria-label", "Ошибка перевода");
      button.append(document.createTextNode("!"));
      return;
    }
    if (record.phase === "queued" || record.phase === "running") {
      const ring = document.createElement("span");
      ring.className = "ring";
      ring.style.setProperty("--p", String(record.progress || 0));
      const caption = document.createElement("span");
      caption.className = "pct";
      caption.textContent = record.phase === "queued"
        ? (record.position ? String(record.position) : "…")
        : `${record.progress || 0}`;
      button.setAttribute("aria-label", record.caption || "Перевод");
      button.append(ring, caption);
      return;
    }
    if (record.phase === "done" && record.showCheck) {
      button.setAttribute("aria-label", "Перевод готов");
      button.append(document.createTextNode("✓"));
      return;
    }
    button.setAttribute("aria-label", record.phase === "done" ? "Действия перевода" : "Перевести изображение");
    button.append(glyph());
  }

  function show(record, phase, caption) {
    record.phase = phase;
    record.caption = caption || "";
    record.host.dataset.state = phase === "queued" ? "running" : phase;
    record.status.textContent = caption || "";
    buttonFace(record);
    place(record);
  }

  async function paintOverlay(record, blob) {
    const bitmap = await createImageBitmap(blob);
    if (!records.has(record.node)) { bitmap.close(); return false; }
    record.bitmap?.close();
    record.bitmap = bitmap;
    record.mode = "overlay";
    record.backgroundKey = "";
    record.canvas.width = bitmap.width;
    record.canvas.height = bitmap.height;
    record.canvas.getContext("2d").drawImage(bitmap, 0, 0);
    record.frame.hidden = false;
    return true;
  }

  function showReady(record) {
    record.showCheck = true;
    show(record, "done", "Готово");
    setTimeout(() => {
      if (records.get(record.node) !== record) return;
      record.showCheck = false;
      applyFade(record);
      buttonFace(record);
    }, 900);
  }

  async function finishResult(record, blob) {
    cache.set(record.imageUrl, blob);
    record.blob = blob;
    record.original = false;
    if (record.node instanceof HTMLImageElement && globalThis.iltNativeSwap) {
      const applied = await globalThis.iltNativeSwap.apply(record.node, blob);
      if (records.get(record.node) !== record) return;
      if (applied?.ok) {
        record.mode = "swap";
        record.frame.hidden = true;
        showReady(record);
        return;
      }
      log("swap-fallback", "подмена не удалась", { url: model.redactUrl?.(record.imageUrl) || record.imageUrl });
    }
    if (!await paintOverlay(record, blob)) return;
    showReady(record);
  }

  function bytesFrom(payload) {
    const binary = atob(payload.imageBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: payload.mime || "image/png" });
  }

  function applyPayload(record, payload) {
    record.progress = typeof payload.progress === "number" ? payload.progress : 0;
    record.position = payload.position || 0;
    const fromCache = payload.stage === "cache";
    const label = model.stageLabel(payload.stage, payload.label, fromCache);
    const eta = model.formatEta(payload.etaMs ?? payload.eta_ms);
    if (payload.status === "queued") {
      show(record, "queued", payload.position ? `В очереди ${payload.position}` : "В очереди");
      return;
    }
    if (payload.status === "running") {
      show(record, "running", eta ? `${label} · ${eta}` : label);
    }
  }

  function waitUpdate(record, revision) {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 4000);
      record.onUpdate = (payload) => {
        clearTimeout(timer);
        if (alive(record, revision)) resolve(payload);
      };
    });
  }

  async function watch(record, force = false) {
    const revision = ++record.revision;
    connectPort();
    show(record, "queued", "В очереди");
    // Смена src или адреса страницы во время очереди не должна оставлять чужой результат.
    const abandon = () => {
      if (alive(record, revision)) return false;
      if (records.get(record.node) === record && record.revision === revision) remove(record);
      return true;
    };
    try {
      const request = {
        type: "translate-url",
        imageUrl: record.imageUrl,
        pageUrl: record.pageUrl,
        force: force,
        imageBase64: record.imageBase64 || undefined,
        imageMime: record.imageMime || undefined,
      };
      let payload = await send(request);
      while (alive(record, revision)) {
        if (!payload) throw new Error("Нет ответа от расширения");
        if (payload.status === "error" || payload.status === "idle") {
          const error = new Error(payload.error || (payload.status === "idle" ? "Задача не найдена. Повторите перевод" : "Ошибка перевода"));
          error.code = payload.errorCode || "";
          throw error;
        }
        if (payload.status === "done") {
          if (abandon()) return;
          await finishResult(record, bytesFrom(payload));
          if (payload.stage === "cache") show(record, "done", "Из кэша");
          return;
        }
        applyPayload(record, payload);
        const next = await waitUpdate(record, revision);
        if (abandon()) return;
        payload = next || await send({ type: "get-status", imageUrl: record.imageUrl, pageUrl: record.pageUrl });
      }
      abandon();
    } catch (error) {
      if (abandon()) return;
      record.errorCode = error.code || "";
      show(record, "error", error.message || "Ошибка перевода");
      record.note.textContent = [error.message, record.errorCode].filter(Boolean).join(" · ");
      record.detail.hidden = false;
      place(record);
      log("translate-error", error.message || "ошибка", { code: record.errorCode });
    }
  }

  function setOriginal(record, on) {
    if (!record.blob || record.phase !== "done") return;
    record.original = on;
    if (record.mode === "swap" && record.node instanceof HTMLImageElement && globalThis.iltNativeSwap) {
      if (on) globalThis.iltNativeSwap.restore(record.node);
      else void globalThis.iltNativeSwap.apply(record.node, record.blob).then((applied) => {
        if (!applied?.ok && records.get(record.node) === record) void paintOverlay(record, record.blob);
      });
    }
    place(record);
  }

  function openPanel(record, on) {
    record.panelOpen = on && record.phase === "done";
    applyFade(record);
    if (record.panelOpen) buttonFace(record);
    place(record);
  }

  function build(node) {
    const host = document.createElement("div");
    host.dataset.iltResult = "";
    host.dataset.iltHover = "";
    host.setAttribute("popover", "manual");
    host.style.cssText = "all:initial;position:fixed;inset:0;width:100vw;height:100vh;margin:0;padding:0;border:0;background:transparent;pointer-events:none;overflow:visible;";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host{color-scheme:light dark}
      :host([data-theme="dark"]), :host([data-theme="system"]){--glass:#172231;--fg:#fff;--line:#ffffff66;--primary:#3890b5}
      :host([data-theme="light"]){--glass:#f4f7fb;--fg:#172231;--line:#1f5f8644;--primary:#0b6fb0}
      @media (prefers-color-scheme: light){:host([data-theme="system"]){--glass:#f4f7fb;--fg:#172231;--line:#1f5f8644;--primary:#0b6fb0}}
      *{box-sizing:border-box}
      [hidden]{display:none!important}
      .frame{position:fixed;pointer-events:none;overflow:hidden}
      canvas{display:block;width:100%;height:100%}
      button.face{position:fixed;width:32px;height:32px;padding:0;border:1px solid var(--line);border-radius:10px;background:color-mix(in srgb,var(--glass) 82%,transparent);color:var(--fg);box-shadow:0 2px 10px #0006;cursor:pointer;pointer-events:auto;display:flex;align-items:center;justify-content:center;transition:opacity .15s}
      .off{opacity:0!important;pointer-events:none!important}
      .off *{pointer-events:none!important}
      button.face.anchored{position:fixed;margin:6px;position-anchor:auto;top:anchor(top);right:anchor(right);left:auto;bottom:auto;position-visibility:anchors-visible}
      button.face.anchored[data-corner="tl"]{left:anchor(left);right:auto}
      button.face.anchored[data-corner="br"]{top:auto;bottom:anchor(bottom);right:anchor(right)}
      button.face.anchored[data-corner="bl"]{top:auto;bottom:anchor(bottom);left:anchor(left);right:auto}
      button.face.bad{background:#8d2b2b;color:#fff}
      .glyph{display:flex;width:20px;height:20px}
      .glyph svg{width:20px;height:20px}
      .ring{position:absolute;inset:3px;border-radius:50%;background:conic-gradient(var(--primary) calc(var(--p)*1%), #0000 0);-webkit-mask:radial-gradient(circle, transparent 58%, #000 60%);mask:radial-gradient(circle, transparent 58%, #000 60%)}
      .pct{position:relative;font:10px/1 system-ui}
      .panel,.detail{position:fixed;display:flex;align-items:center;max-width:calc(100vw - 16px);gap:2px;padding:0 4px;border-radius:10px;background:color-mix(in srgb,var(--glass) 92%,transparent);color:var(--fg);box-shadow:0 2px 10px #0006;pointer-events:auto;transition:opacity .15s}
      .panel{height:32px;flex-wrap:nowrap;white-space:nowrap;border:1px solid var(--line)}
      .detail{min-height:32px;flex-wrap:wrap;padding:4px;max-width:min(360px,calc(100vw - 16px))}
      .note{font:12px/1.3 system-ui;padding:0 6px;flex-basis:100%}
      .panel button,.detail button{font:12px/1.2 system-ui;color:inherit;background:transparent;border:0;border-radius:8px;padding:4px 6px;cursor:pointer;pointer-events:auto}
      .status{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
    `;
    const frame = document.createElement("div");
    frame.className = "frame";
    const canvas = document.createElement("canvas");
    frame.append(canvas);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "face";
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.hidden = true;
    const names = [
      ["compare", "Сравнить"],
      ["copy", "Копировать"],
      ["save", "Сохранить"],
      ["again", "Перевести заново"],
      ["close", "Убрать"],
      ["more", "Ещё"],
    ];
    const actions = {};
    for (let i = 0; i < names.length; i += 1) {
      const item = document.createElement("button");
      item.type = "button";
      item.textContent = names[i][0] === "more" ? "⋯" : names[i][1];
      item.setAttribute("aria-label", names[i][1]);
      item.title = names[i][1];
      actions[names[i][0]] = item;
      panel.append(item);
    }
    const menu = document.createElement("button");
    menu.type = "button";
    menu.textContent = "Не показывать на этом сайте";
    menu.hidden = true;
    panel.append(menu);
    const detail = document.createElement("div");
    detail.className = "detail";
    detail.hidden = true;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Повторить";
    const saveLog = document.createElement("button");
    saveLog.type = "button";
    saveLog.textContent = "Сохранить логи";
    const note = document.createElement("span");
    note.className = "note";
    detail.append(note, retry, saveLog);
    const status = document.createElement("span");
    status.className = "status";
    status.setAttribute("role", "status");
    shadow.append(style, frame, button, panel, detail, status);
    const record = {
      node, host, frame, canvas, button, panel, detail, note, status, retry, menu, actions, clipped: false,
      bitmap: null, blob: null, mode: "overlay", phase: "idle", corner: "tr",
      imageUrl: "", pageUrl: location.href, source: () => "", revision: 0,
      original: false, permitted: false, panelOpen: false, faceShown: false, showCheck: false,
      progress: 0, position: 0, caption: "", errorCode: "", anchored: false,
      imageBase64: "", imageMime: "",
    };
    for (const item of [button, ...Object.values(actions), retry, saveLog, menu]) {
      item.addEventListener("pointerdown", stop);
      item.addEventListener("mousedown", stop);
      item.addEventListener("click", (event) => {
        if (!event.isTrusted) { stop(event); return; }
        stop(event);
      });
    }
    button.addEventListener("click", (event) => {
      if (!event.isTrusted) return;
      if (record.phase === "idle") void watch(record, false);
      else if (record.phase === "error") {
        detail.hidden = !detail.hidden;
        place(record);
      } else if (record.phase === "done") openPanel(record, true);
    });
    actions.close.addEventListener("click", () => {
      const imageUrl = record.imageUrl;
      remove(record);
      if (!(node instanceof HTMLImageElement) || !nearBox(node, 0)) return;
      const fresh = ensure(node);
      fresh.imageUrl = imageUrl;
      fresh.pageUrl = location.href.split("#")[0];
      fresh.source = () => fresh.imageUrl;
      show(fresh, "idle", "");
    });
    actions.again.addEventListener("click", () => { openPanel(record, false); void watch(record, true); });
    actions.copy.addEventListener("click", () => {
      if (!record.blob || !navigator.clipboard?.write || typeof ClipboardItem !== "function") return;
      const type = record.blob.type || "image/png";
      void navigator.clipboard.write([new ClipboardItem({ [type]: record.blob })]).catch(() => {});
    });
    actions.save.addEventListener("click", () => {
      void send({ type: "save-result", imageUrl: record.imageUrl, pageUrl: record.pageUrl });
    });
    actions.compare.addEventListener("pointerdown", () => setOriginal(record, true));
    actions.compare.addEventListener("pointerup", () => setOriginal(record, false));
    actions.compare.addEventListener("pointerleave", () => { if (record.original) setOriginal(record, false); });
    actions.more.addEventListener("click", () => { menu.hidden = !menu.hidden; place(record); });
    menu.addEventListener("click", () => { void excludeSite(); });
    retry.addEventListener("click", () => {
      if (!record.permitted) return;
      detail.hidden = true;
      void watch(record, true);
    });
    saveLog.addEventListener("click", () => { void globalThis.iltLog?.save(); });
    record.observer = new ResizeObserver(() => place(record));
    record.observer.observe(node);
    return record;
  }

  function mount(record) {
    const parent = record.node.closest("dialog[open]") || document.fullscreenElement || document.documentElement;
    parent.append(record.host);
    applyTheme(record.host);
    try { record.host.showPopover(); } catch (_) {}
    record.anchored = useAnchor(record);
    place(record);
  }

  function ensure(node) {
    const existing = records.get(node);
    if (existing) return existing;
    const record = build(node);
    records.set(node, record);
    mount(record);
    return record;
  }

  async function readInlineBytes(choice) {
    if (choice.imageBase64) return { imageBase64: choice.imageBase64, imageMime: choice.imageMime || "image/png" };
    const url = choice.url || "";
    if (!url.startsWith("blob:") && !url.startsWith("data:")) return {};
    try {
      const response = await fetch(url);
      const blob = await response.blob();
      const buffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x2000) {
        binary += String.fromCharCode.apply(null, bytes.subarray(offset, offset + 0x2000));
      }
      return { imageBase64: btoa(binary), imageMime: blob.type || "image/png" };
    } catch (error) {
      log("read-bytes", error.message || "не прочитано", {});
      return {};
    }
  }

  async function start(choice, permitted = false, error = "") {
    const node = choice.node;
    const record = ensure(node);
    record.imageUrl = choice.url || "";
    record.pageUrl = location.href.split("#")[0];
    record.source = choice.source || (() => record.imageUrl);
    watchAddress(record);
    record.permitted = permitted;
    record.phase = "queued";
    const bytes = await readInlineBytes(choice);
    record.imageBase64 = bytes.imageBase64 || "";
    record.imageMime = bytes.imageMime || "";
    if (error) {
      show(record, "error", error);
      record.detail.hidden = false;
      record.note.textContent = error;
      place(record);
      return record;
    }
    if (permitted) void watch(record, false);
    else {
      show(record, "error", "Нужен доступ к изображению и серверу");
      record.retry.textContent = "Разрешить и перевести";
      record.detail.hidden = false;
      record.retry.onclick = () => {
        record.retry.disabled = true;
        void send({ type: "requestHost", origins: choice.origins || [] }).then((payload) => {
          if (!payload?.granted) throw new Error(payload?.error || "Доступ не разрешён");
          record.permitted = true;
          record.detail.hidden = true;
          record.retry.textContent = "Повторить";
          return watch(record, false);
        }).catch((failure) => {
          if (alive(record)) show(record, "error", failure.message);
        }).finally(() => { record.retry.disabled = false; });
      };
    }
    return record;
  }

  function preview(img) {
    if (!(img instanceof Element)) return;
    const existing = records.get(img);
    if (existing && existing.phase === "done") {
      if (!existing.faceShown) {
        existing.faceShown = true;
        applyFade(existing);
        place(existing);
      }
      return;
    }
    if (existing && existing.phase !== "idle") return;
    const record = ensure(img);
    if (record.phase !== "idle") return;
    record.imageUrl = globalThis.iltNativeSwap?.originalUrl?.(img) || img.currentSrc || img.src || "";
    record.pageUrl = location.href.split("#")[0];
    record.source = () => record.imageUrl;
    show(record, "idle", "");
  }

  function hidePreview(img) {
    if (pointerOnButton()) return;
    const record = img ? records.get(img) : null;
    const targets = record ? [record] : [...records.values()].filter((item) => item.phase === "idle" || item.faceShown || item.panelOpen);
    for (const target of targets) {
      if (target.phase === "idle") { remove(target); continue; }
      target.faceShown = false;
      openPanel(target, false);
    }
  }

  function pointerOnButton() {
    for (const record of records.values()) {
      const visible = !record.button.hidden && !record.button.classList.contains("off");
      const overButton = visible && nearBox(record.button, 0);
      const overPanel = record.panelOpen && nearBox(record.panel, PANEL_ZONE);
      if (overButton || overPanel) return true;
    }
    return false;
  }

  function findSave(srcUrl) {
    const wanted = String(srcUrl || "");
    for (const record of records.values()) {
      if (!record.blob) continue;
      const swap = globalThis.iltNativeSwap;
      const urls = [record.imageUrl, swap?.blobUrl?.(record.node), swap?.originalUrl?.(record.node)];
      if (record.node instanceof HTMLImageElement) urls.push(record.node.currentSrc, record.node.src);
      if (urls.includes(wanted)) return { ok: true, imageUrl: record.imageUrl, pageUrl: record.pageUrl };
    }
    return { ok: false, error: "нет перевода" };
  }

  function underPointer() {
    const stack = document.elementsFromPoint(pointer.x, pointer.y);
    for (let i = 0; i < stack.length; i += 1) {
      const node = stack[i];
      if (node instanceof HTMLImageElement) return node;
    }
    return null;
  }

  function setCompare(on) {
    for (const record of records.values()) {
      if (record.phase === "done" && record.blob) setOriginal(record, on);
    }
  }

  async function excludeSite() {
    const host = location.hostname;
    const data = await storageGet({ hoverDisabledSites: [] });
    const list = Array.isArray(data.hoverDisabledSites) ? data.hoverDisabledSites.slice() : [];
    if (!list.includes(host)) list.push(host);
    await new Promise((resolve) => {
      const response = ext.storage.local.set({ hoverDisabledSites: list }, resolve);
      if (response?.then) response.then(resolve, resolve);
    });
    for (const record of [...records.values()]) {
      if (record.phase === "idle") remove(record);
    }
  }

  function count() {
    let ready = 0;
    let errors = 0;
    for (const record of records.values()) {
      if (record.blob) ready += 1;
      if (record.phase === "error") errors += 1;
    }
    return { count: ready, errors: errors };
  }

  function showOriginals(on) {
    for (const record of records.values()) setOriginal(record, !!on);
  }

  function removeAll() {
    for (const record of [...records.values()]) remove(record);
  }

  globalThis.iltNativeSwap?.onChange?.((event) => {
    const record = records.get(event.img);
    if (!record) return;
    if (event.type === "fallback") {
      log("swap-fallback", "сайт вернул исходный адрес", {});
      if (record.blob) void paintOverlay(record, record.blob).then(() => place(record));
      return;
    }
    if (event.type !== "new-image") return;
    const blob = cache.get(event.url);
    if (blob) {
      record.imageUrl = event.url;
      record.source = () => event.url;
      void finishResult(record, blob);
      return;
    }
    remove(record);
  });

  window.addEventListener("pagehide", () => { for (const record of [...records.values()]) remove(record); });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Alt" && event.isTrusted) setCompare(true);
  }, true);
  window.addEventListener("keyup", (event) => {
    if (event.key === "Alt") setCompare(false);
  }, true);
  window.addEventListener("blur", () => setCompare(false));

  readTheme();
  if (ext.storage?.onChanged) {
    ext.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.theme) readTheme();
    });
  }

  globalThis.iltInlineContent = {
    start: start,
    has: (node) => records.has(node) && records.get(node).phase !== "idle",
    findSave: findSave,
    preview: preview,
    hidePreview: hidePreview,
    pointerOnButton: pointerOnButton,
    underPointer: underPointer,
    setCompare: setCompare,
    count: count,
    showOriginals: showOriginals,
    removeAll: removeAll,
  };
})();
