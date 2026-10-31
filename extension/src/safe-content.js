// Явный выбор и результат на месте без изменения источников страницы.
(() => {
  "use strict";
  const ext = globalThis.chrome ?? globalThis.browser;
  let cancel = () => {};
  let contextChoice = null;
  const selections = new WeakMap();

  const DECOR_NAME = /icon|sprite|emoji|avatar/i;
  let hoverAllowed = false;
  let hoverDelayMs = 220;
  let hoverMinLong = 160;
  let hoverTarget = null;
  let hoverCandidate = null;
  let hoverTimer = 0;
  let hideTimer = 0;
  let hoverPoint = { x: 0, y: 0 };
  let pointerDown = false;
  let selecting = false;

  function storageGet(defaults) {
    return new Promise((resolve, reject) => {
      const response = ext.storage.local.get(defaults, value => {
        const error = ext.runtime.lastError;
        if (error) reject(new Error(error.message)); else resolve(value || {});
      });
      if (response?.then) response.then(resolve, reject);
    });
  }

  function readHoverAllowed() {
    if (!ext.storage?.local) return;
    storageGet({ buttonEnabled: true, hoverDisabledSites: [], hoverDelayMs: 220, hoverMinLong: 160 }).then(value => {
      const disabled = Array.isArray(value.hoverDisabledSites) ? value.hoverDisabledSites : [];
      hoverDelayMs = Number(value.hoverDelayMs) > 0 ? Number(value.hoverDelayMs) : 220;
      hoverMinLong = Number(value.hoverMinLong) > 0 ? Number(value.hoverMinLong) : 160;
      hoverAllowed = value.buttonEnabled !== false && !disabled.includes(location.hostname);
    }).catch(() => { hoverAllowed = false; });
  }

  function source(node) {
    if (node instanceof HTMLImageElement) {
      return globalThis.iltNativeSwap?.originalUrl(node) || node.currentSrc || node.src;
    }
    if (node instanceof HTMLCanvasElement) return `${node.width}x${node.height}`;
    return getComputedStyle(node).backgroundImage;
  }

  async function translate(choice, message = {}) {
    globalThis.iltInlineContent?.hidePreview?.(choice.node);
    const revision = {};
    selections.set(choice.node, revision);
    let imageUrl = choice.url || "";
    let error = "";
    if (choice.canvas) {
      try { imageUrl = choice.node.toDataURL("image/png"); }
      catch (_) { error = "Этот холст защищён сайтом от чтения"; }
      if (imageUrl === "data:,") error = "Холст пуст";
    }
    const fingerprint = source(choice.node);
    if (choice.node instanceof HTMLImageElement && fingerprint !== imageUrl) return;
    const capturedPage = location.href;
    const send = (request) => new Promise((resolve, reject) => {
      let settled = false;
      const finish = (value, error) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(value);
      };
      let pending;
      try {
        pending = ext.runtime.sendMessage(request, (value) => {
          const failure = ext.runtime.lastError;
          if (failure) finish(undefined, new Error(failure.message));
          else finish(value);
        });
      } catch (error) {
        finish(undefined, error);
        return;
      }
      if (pending?.then) pending.then((value) => { if (value !== undefined) finish(value); }, (error) => finish(undefined, error));
    });
    try {
      const payload = await send({ type: "image-selected", imageUrl, pageUrl: capturedPage, error, inline: true });
      const settings = await storageGet({ serverUrl: "http://127.0.0.1:8765" });
      if (selections.get(choice.node) !== revision || !choice.node.isConnected || source(choice.node) !== fingerprint || location.href !== capturedPage) return;
      const origins = [];
      for (const address of [imageUrl, settings.serverUrl]) {
        try { const url = new URL(address); if (/^https?:$/.test(url.protocol)) origins.push(url.origin + "/*"); }
        catch (_) { /* ошибку адреса покажет очередь */ }
      }
      globalThis.iltInlineContent?.start({ ...choice, url: imageUrl, origins: [...new Set(origins)],
        source: () => source(choice.node) === fingerprint ? imageUrl : "" }, message.permitted === true || payload?.permitted === true, error);
    } catch (failure) {
      if (selections.get(choice.node) !== revision || !choice.node.isConnected) return;
      globalThis.iltInlineContent?.start({ ...choice, url: imageUrl, source: () => imageUrl }, false, failure.message);
    }
  }

  function candidate(target) {
    for (let node = target; node instanceof Element; node = node.parentElement) {
      if (node instanceof HTMLImageElement) {
        return { node, url: globalThis.iltNativeSwap?.originalUrl(node) || node.currentSrc || node.src };
      }
      if (node instanceof HTMLCanvasElement) return { node, canvas: true };
      const background = getComputedStyle(node).backgroundImage;
      const match = /^url\(\s*(?:"([^"]+)"|'([^']+)'|([^()]+))\s*\)$/.exec(background);
      if (match) return { node, url: new URL(match[1] || match[2] || match[3], document.baseURI).href };
    }
    return null;
  }

  function hasResult(img) {
    return globalThis.iltInlineContent?.has?.(img) === true;
  }

  function insideRect(rect, x, y) {
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  function eligibleImage(img) {
    if (!(img instanceof HTMLImageElement) || !img.isConnected) return false;
    if (!img.complete || Math.max(img.naturalWidth || 0, img.naturalHeight || 0) <= 180) return false;
    const address = globalThis.iltNativeSwap?.originalUrl(img) || img.currentSrc || img.src;
    if (!address || (address.startsWith("blob:") && !globalThis.iltNativeSwap?.isSwapped(img))) return false;
    const rect = img.getBoundingClientRect();
    const longSide = Math.max(rect.width, rect.height);
    const shortSide = Math.min(rect.width, rect.height);
    if (longSide < hoverMinLong || shortSide < 80) return false;
    if (img.getAttribute("aria-hidden") === "true") return false;
    const role = String(img.getAttribute("role") || "").toLowerCase();
    if (role === "presentation" || role === "none") return false;
    const name = [String(img.className || ""), img.id, img.getAttribute("alt") || ""].join(" ");
    if (DECOR_NAME.test(name)) return false;
    if (longSide < 400 && (img.parentElement?.tagName === "BUTTON"
      || img.closest("nav, header, footer, [role='banner'], [role='navigation'], [role='contentinfo']"))) return false;
    return true;
  }

  function hoverUi() {
    return globalThis.iltInlineContent;
  }

  function blockedGesture() {
    if (selecting || pointerDown) return true;
    const active = document.activeElement;
    if (active?.matches?.('input, textarea, select, [contenteditable=true]')) return true;
    const selection = document.getSelection?.();
    if (selection && !selection.isCollapsed) return true;
    const full = document.fullscreenElement;
    if (full && full.querySelector?.('video')) return true;
    return false;
  }

  function resultAt(x, y) {
    const stack = document.elementsFromPoint(x, y);
    const ui = document.querySelector("[data-ilt-hover]");
    for (let i = 0; i < stack.length; i += 1) {
      const node = stack[i];
      if (ui && (node === ui || ui.contains(node))) continue;
      if (hoverUi()?.has?.(node)) return node;
    }
    return null;
  }

  function imageAt(x, y) {
    const stack = document.elementsFromPoint(x, y);
    const ui = document.querySelector('[data-ilt-hover]');
    for (let i = 0; i < stack.length; i += 1) {
      const node = stack[i];
      if (ui && (node === ui || ui.contains(node))) continue;
      if (node instanceof HTMLImageElement) return node;
    }
    return null;
  }

  function scheduleHide() {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      hideTimer = 0;
      if (hoverUi()?.pointerOnButton?.()) return;
      hoverTarget = null;
      hoverUi()?.hidePreview?.();
    }, 300);
  }

  function processHoverPointer() {
    if (!hoverAllowed || blockedGesture()) {
      hoverUi()?.hidePreview?.();
      return;
    }
    if (hoverUi()?.pointerOnButton?.()) return;
    const img = imageAt(hoverPoint.x, hoverPoint.y) || resultAt(hoverPoint.x, hoverPoint.y);
    const known = Boolean(img && hoverUi()?.has?.(img));
    if (!img || (!known && !eligibleImage(img))) {
      hoverCandidate = null;
      if (hoverTimer) clearTimeout(hoverTimer);
      hoverTimer = 0;
      if (hoverTarget) scheduleHide();
      return;
    }
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = 0; }
    if (img === hoverTarget || img === hoverCandidate) {
      if (known) hoverUi()?.preview?.(img);
      return;
    }
    hoverCandidate = img;
    if (hoverTimer) clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      hoverTimer = 0;
      if (!hoverAllowed || blockedGesture() || hoverCandidate !== img || !img.isConnected) return;
      if (!hoverUi()?.has?.(img) && !eligibleImage(img)) return;
      hoverTarget = img;
      hoverUi()?.preview?.(img);
    }, hoverDelayMs);
  }

  let hoverPointerFrame = 0;

  function onHoverMove(event) {
    if (!event.isTrusted) return;
    hoverPoint = { x: event.clientX, y: event.clientY };
    if (hoverPointerFrame) return;
    hoverPointerFrame = requestAnimationFrame(() => {
      hoverPointerFrame = 0;
      if (!hoverAllowed || selecting) { hoverUi()?.hidePreview?.(); return; }
      processHoverPointer();
    });
  }

  function onHoverDown(event) {
    if (!event.isTrusted) return;
    if (hoverUi()?.pointerOnButton?.()) return;
    pointerDown = true;
    hoverUi()?.hidePreview?.();
  }

  function onHoverUp(event) {
    if (event && !event.isTrusted) return;
    pointerDown = false;
  }


  function start() {
    cancel();
    selecting = true;
    hoverUi()?.hidePreview?.();
    const host = document.createElement("div");
    host.dataset.iltSelector = "";
    // Top layer использует viewport даже при transform у html/body.
    host.setAttribute("popover", "manual");
    host.style.cssText = "all:initial!important;position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;border:0!important;background:transparent!important;pointer-events:none!important;overflow:visible!important;z-index:2147483647!important";
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = ":host::backdrop{background:transparent;pointer-events:none}div{position:fixed;box-sizing:border-box;border:2px solid #4285f4;pointer-events:none;background:#4285f414}";
    const frame = document.createElement("div");
    frame.hidden = true;
    shadow.append(style, frame);
    document.documentElement.append(host);
    if (host.showPopover) host.showPopover();
    let selected = null;
    let point = null;
    let animation = 0;
    const move = (event) => { point = { x: event.clientX, y: event.clientY }; };
    const draw = () => {
      selected = point ? candidate(document.elementFromPoint(point.x, point.y)) : null;
      frame.hidden = !selected;
      if (selected) {
        const rect = selected.node.getBoundingClientRect();
        frame.style.cssText = `left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px`;
      }
      animation = requestAnimationFrame(draw);
    };
    const stop = () => {
      cancelAnimationFrame(animation);
      host.remove();
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerdown", block, true);
      window.removeEventListener("mousedown", block, true);
      window.removeEventListener("pointerup", block, true);
      window.removeEventListener("mouseup", block, true);
      window.removeEventListener("click", choose, true);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("pagehide", stop);
      selecting = false;
      cancel = () => {};
    };
    const block = (event) => {
      if (!candidate(event.target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    const choose = (event) => {
      const choice = candidate(event.target);
      if (!choice) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      stop();
      void translate(choice);
    };
    const key = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      stop();
    };
    cancel = stop;
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerdown", block, true);
    window.addEventListener("mousedown", block, true);
    window.addEventListener("pointerup", block, true);
    window.addEventListener("mouseup", block, true);
    window.addEventListener("click", choose, true);
    window.addEventListener("keydown", key, true);
    window.addEventListener("pagehide", stop);
    animation = requestAnimationFrame(draw);
  }

  globalThis.iltSafeContent = {
    init() {
      readHoverAllowed();
      window.addEventListener("contextmenu", event => {
        if (!event.isTrusted) return;
        contextChoice = candidate(event.target);
        const node = contextChoice?.node;
        const saved = node ? hoverUi()?.findSave?.(source(node)) : null;
        try { ext.runtime.sendMessage({ type: "context-target", hasTranslation: saved?.ok === true }); } catch (_) {}
      }, true);
      window.addEventListener("pointermove", onHoverMove, true);
      window.addEventListener("pointerdown", onHoverDown, true);
      window.addEventListener("pointerup", onHoverUp, true);
      window.addEventListener("blur", () => hoverUi()?.hidePreview?.());
      window.addEventListener("pagehide", () => hoverUi()?.hidePreview?.());
      document.addEventListener("mouseleave", () => hoverUi()?.hidePreview?.());
      if (ext.storage?.onChanged) {
        ext.storage.onChanged.addListener((changes, area) => {
          if (area === "local" && (changes.hoverDisabledSites || changes.buttonEnabled || changes.hoverDelayMs || changes.hoverMinLong)) readHoverAllowed();
        });
      }
      ext.runtime.onMessage.addListener((message, _sender, reply) => {
        if (message?.type === "inline-save") {
          reply(globalThis.iltInlineContent?.findSave?.(message.srcUrl) || { ok: false, error: "нет перевода" });
          return;
        }
        if (message?.type === "page-summary") {
          reply(hoverUi()?.count?.() || { count: 0, errors: 0 });
          return;
        }
        if (message?.type === "show-originals") {
          hoverUi()?.showOriginals?.(message.on === true);
          reply({ ok: true });
          return;
        }
        if (message?.type === "remove-all") {
          hoverUi()?.removeAll?.();
          reply({ ok: true });
          return;
        }
        if (message?.type === "translate-hovered") {
          const img = hoverUi()?.underPointer?.();
          if (!img || !eligibleImage(img)) { reply({ ok: false }); return; }
          void translate(candidate(img) || { node: img, url: source(img) }, { permitted: true });
          reply({ ok: true });
          return;
        }
        if (message?.type === "translate-inline") {
          let choice = contextChoice;
          if (!choice?.node.isConnected || choice.url !== message.imageUrl) {
            const matches = [...document.images].filter(img => {
              const urls = [img.currentSrc, img.src, globalThis.iltNativeSwap?.originalUrl(img)];
              return urls.includes(message.imageUrl);
            });
            choice = matches.length === 1 ? candidate(matches[0]) : null;
          }
          contextChoice = null;
          if (!choice) { reply({ ok: false, error: "Не удалось найти выбранное изображение. Используйте «Выбрать изображение»" }); return; }
          void translate(choice, message);
          reply({ ok: true });
          return;
        }
        if (message?.type !== "select-image") return;
        // tabs.sendMessage без frameId получает каждый frame: ручной выбор нужен только верхнему.
        if (window !== window.top) return;
        start();
        reply({ ok: true });
      });
    },
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => globalThis.iltSafeContent.init(), { once: true });
  else globalThis.iltSafeContent.init();
})();
