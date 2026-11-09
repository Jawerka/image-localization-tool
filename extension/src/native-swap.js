// Подмена src/srcset выбранного img без сдвига внутреннего размера.
(() => {
  "use strict";

  const records = new WeakMap();
  const urlRefs = new Map();
  const listeners = new Set();
  let selfWrite = 0;

  function isImg(node) {
    return Boolean(node) && node.tagName === "IMG";
  }

  function attr(node, name) {
    return node.hasAttribute(name) ? node.getAttribute(name) : null;
  }

  function writeAttr(node, name, value) {
    if (value == null) node.removeAttribute(name);
    else node.setAttribute(name, value);
  }

  function pictureOf(img) {
    return typeof img.closest === "function" ? img.closest("picture") : null;
  }

  function pictureSources(img) {
    const picture = pictureOf(img);
    if (!picture) return [];
    return [...picture.children].filter(node => node.tagName === "SOURCE");
  }

  function snapshot(img) {
    return {
      src: attr(img, "src"),
      srcset: attr(img, "srcset"),
      sizes: attr(img, "sizes"),
      sources: pictureSources(img).map(node => ({
        node,
        srcset: attr(node, "srcset"),
        sizes: attr(node, "sizes"),
        type: attr(node, "type"),
      })),
    };
  }

  function withSelfWrite(fn) {
    selfWrite += 1;
    try { return fn(); }
    finally { queueMicrotask(() => { selfWrite = Math.max(0, selfWrite - 1); }); }
  }

  function restoreAttrs(img, snap) {
    withSelfWrite(() => {
      writeAttr(img, "srcset", snap.srcset);
      writeAttr(img, "sizes", snap.sizes);
      writeAttr(img, "src", snap.src);
      for (const source of snap.sources) {
        if (!source.node.isConnected) continue;
        writeAttr(source.node, "srcset", source.srcset);
        writeAttr(source.node, "sizes", source.sizes);
        writeAttr(source.node, "type", source.type);
      }
    });
  }

  function retain(url) {
    if (!url) return;
    urlRefs.set(url, (urlRefs.get(url) || 0) + 1);
  }

  function release(url) {
    if (!url) return;
    const next = (urlRefs.get(url) || 1) - 1;
    if (next <= 0) {
      urlRefs.delete(url);
      try { URL.revokeObjectURL(url); } catch (_) { /* URL мог быть data: */ }
    } else urlRefs.set(url, next);
  }

  function absolute(value) {
    if (!value) return "";
    try { return new URL(value, document.baseURI).href; }
    catch (_) { return String(value); }
  }

  function sameUrl(left, right) {
    if (!left || !right) return left === right;
    return absolute(left) === absolute(right);
  }

  function originalAddress(record) {
    return absolute(record.snapshot.src || record.currentSrc || "");
  }

  function emit(event) {
    for (const listener of listeners) {
      try { listener(event); }
      catch (_) { /* слушатель не должен ломать подмену */ }
    }
  }

  async function decodeUrl(url) {
    const probe = new Image();
    probe.src = url;
    if (typeof probe.decode === "function") await probe.decode();
    else {
      await new Promise((resolve, reject) => {
        probe.onload = resolve;
        probe.onerror = () => reject(new Error("Не удалось декодировать перевод"));
      });
    }
    return probe;
  }

  async function measurePixels(img, record) {
    if (record?.pixelWidth && record?.pixelHeight) {
      return { width: record.pixelWidth, height: record.pixelHeight };
    }
    const url = img.currentSrc || img.src;
    if (!url) return { width: img.naturalWidth, height: img.naturalHeight };
    try {
      const probe = await decodeUrl(url);
      return {
        width: probe.naturalWidth || img.naturalWidth,
        height: probe.naturalHeight || img.naturalHeight,
      };
    } catch (_) {
      return { width: img.naturalWidth, height: img.naturalHeight };
    }
  }

  async function normalizeBlob(blob, width, height) {
    const bitmap = await createImageBitmap(blob);
    try {
      if (bitmap.width === width && bitmap.height === height) {
        return { blob, width: bitmap.width, height: bitmap.height };
      }
      const Canvas = globalThis.OffscreenCanvas;
      const canvas = Canvas ? new Canvas(width, height) : Object.assign(document.createElement("canvas"), { width, height });
      const context = canvas.getContext("2d");
      context.drawImage(bitmap, 0, 0, width, height);
      const out = canvas.convertToBlob
        ? await canvas.convertToBlob({ type: "image/png" })
        : await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      return { blob: out, width, height };
    } finally {
      bitmap.close();
    }
  }

  function waitLoad(img, blobUrl) {
    if ((img.currentSrc === blobUrl || img.src === blobUrl) && img.complete && img.naturalWidth > 0) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const done = (ok) => {
        img.removeEventListener("load", onLoad);
        img.removeEventListener("error", onError);
        ok ? resolve() : reject(new Error("Страница запретила подмену изображения"));
      };
      const onLoad = () => done(true);
      const onError = () => done(false);
      img.addEventListener("load", onLoad);
      img.addEventListener("error", onError);
    });
  }

  function startObserver(img, record) {
    if (typeof MutationObserver !== "function") return;
    record.observer?.disconnect();
    const observer = new MutationObserver(() => {
      if (selfWrite > 0) return;
      if (records.get(img) !== record) return;
      handleSiteWrite(img, record);
    });
    observer.observe(img, { attributes: true, attributeFilter: ["src", "srcset", "sizes"] });
    for (const source of pictureSources(img)) {
      observer.observe(source, { attributes: true, attributeFilter: ["srcset", "sizes", "type"] });
    }
    const picture = pictureOf(img);
    if (picture) observer.observe(picture, { childList: true });
    record.observer = observer;
  }

  function handleSiteWrite(img, record) {
    const srcAttr = attr(img, "src") || "";
    const srcsetAttr = attr(img, "srcset") || "";
    const sourceChanged = pictureSources(img).some(node => (attr(node, "srcset") || "") !== record.srcsetValue);
    if (sameUrl(srcAttr, record.blobUrl) && srcsetAttr === record.srcsetValue && !sourceChanged) return;
    const now = srcAttr || img.currentSrc || "";
    const original = originalAddress(record);
    const originalSrcset = record.snapshot.srcset || "";
    const nowSrcset = srcsetAttr;
    if (sameUrl(now, original) || (originalSrcset && nowSrcset === originalSrcset && !String(now).startsWith("blob:"))) {
      const stamp = Date.now();
      if (stamp - record.retryAt > 2000) {
        record.retries = 0;
        record.retryAt = stamp;
      }
      record.retries += 1;
      if (record.retries > 3) {
        restore(img);
        emit({ type: "fallback", img });
        return;
      }
      void apply(img, record.blob);
      return;
    }
    const changedSource = pictureSources(img).find(node => (attr(node, "srcset") || "") !== record.srcsetValue);
    const next = absolute(changedSource ? (attr(changedSource, "srcset") || now) : now);
    detach(img);
    emit({ type: "new-image", img, url: next });
  }

  function detach(img) {
    const record = records.get(img);
    if (!record) return;
    record.observer?.disconnect();
    records.delete(img);
    release(record.blobUrl);
  }

  function restore(img) {
    const record = records.get(img);
    if (!record) return;
    record.observer?.disconnect();
    restoreAttrs(img, record.snapshot);
    records.delete(img);
    release(record.blobUrl);
  }

  async function apply(img, blob) {
    if (!isImg(img) || !blob) return { ok: false, error: "Нет изображения" };
    const previous = records.get(img);
    const snap = previous?.snapshot || snapshot(img);
    const naturalWidth = previous?.naturalWidth || img.naturalWidth;
    const naturalHeight = previous?.naturalHeight || img.naturalHeight;
    if (!naturalWidth || !naturalHeight) return { ok: false, error: "Нет размера изображения" };
    // currentSrc после подмены blob может быть верным, а рисуется всё ещё <source type="image/webp">.
    if (pictureSources(img).length) {
      return { ok: false, error: "Страница показывает изображение через picture" };
    }
    let pixels;
    try { pixels = await measurePixels(img, previous); }
    catch (_) { pixels = { width: naturalWidth, height: naturalHeight }; }
    if (!pixels.width || !pixels.height) return { ok: false, error: "Нет размера изображения" };
    let normalized;
    try { normalized = await normalizeBlob(blob, pixels.width, pixels.height); }
    catch (error) { return { ok: false, error: error.message || "Не удалось подготовить перевод" }; }
    const url = URL.createObjectURL(normalized.blob);
    try { await decodeUrl(url); }
    catch (error) {
      URL.revokeObjectURL(url);
      return { ok: false, error: error.message || "Не удалось декодировать перевод" };
    }
    const d = pixels.width / naturalWidth;
    const density = Number.isFinite(d) && d > 0 ? d : 1;
    const srcsetValue = `${url} ${density}x`;
    if (previous) {
      previous.observer?.disconnect();
      records.delete(img);
      release(previous.blobUrl);
    }
    const record = {
      snapshot: snap,
      blob: normalized.blob,
      blobUrl: url,
      srcsetValue,
      naturalWidth,
      naturalHeight,
      pixelWidth: pixels.width,
      pixelHeight: pixels.height,
      currentSrc: img.currentSrc || img.src,
      retries: previous?.retries || 0,
      retryAt: previous?.retryAt || Date.now(),
      observer: null,
    };
    retain(url);
    records.set(img, record);
    try {
      const loading = waitLoad(img, url);
      withSelfWrite(() => {
        img.setAttribute("srcset", srcsetValue);
        for (const source of pictureSources(img)) source.setAttribute("srcset", srcsetValue);
        img.src = url;
      });
      await loading;
      if (typeof img.decode === "function") await img.decode().catch(() => {});
      if (records.get(img) !== record) return { ok: false, error: "Подмена устарела" };
      const widthOk = Math.abs((img.naturalWidth || 0) - naturalWidth) <= 1;
      const heightOk = Math.abs((img.naturalHeight || 0) - naturalHeight) <= 1;
      const srcOk = sameUrl(img.currentSrc, url);
      if (!srcOk || !widthOk || !heightOk) throw new Error("Страница запретила подмену изображения");
    } catch (error) {
      restore(img);
      return { ok: false, error: error.message || "Страница запретила подмену изображения" };
    }
    startObserver(img, record);
    return { ok: true, blobUrl: url };
  }

  globalThis.iltNativeSwap = {
    apply,
    restore,
    detach,
    isSwapped: img => records.has(img),
    originalUrl: img => {
      const record = records.get(img);
      return record ? originalAddress(record) : "";
    },
    blobUrl: img => records.get(img)?.blobUrl || "",
    onChange: listener => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
})();
