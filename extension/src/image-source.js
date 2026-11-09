// Читаем исходник в контексте страницы, пока доступен её HTTP-кэш или декодированный IMG.
(() => {
  "use strict";
  const MAX_INLINE_BYTES = 32 * 1024 * 1024;
  const PAGE_FETCH_TIMEOUT_MS = 5000;

  function address(node) {
    return node ? [node.currentSrc || "", node.src || "", node.srcset || ""].join("\n") : "";
  }

  async function encode(blob) {
    if (!blob?.size || blob.size > MAX_INLINE_BYTES) throw new Error("E_INLINE_SIZE");
    if (blob.type && !/^image\//i.test(blob.type) && blob.type !== "application/octet-stream") {
      throw new Error("E_IMAGE_TYPE");
    }
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x2000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(offset, offset + 0x2000));
    }
    return { imageBase64: btoa(binary), imageMime: blob.type || "image/png" };
  }

  async function read(choice, log = () => {}) {
    if (choice.imageBase64) return { imageBase64: choice.imageBase64, imageMime: choice.imageMime || "image/png" };
    const url = choice.url || "";
    if (!/^(https?:|blob:|data:)/i.test(url)) return {};
    const node = choice.node;
    const originalAddress = address(node);
    const unchanged = () => !node || (node.isConnected !== false && address(node) === originalAddress);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PAGE_FETCH_TIMEOUT_MS);
    try {
      // force-cache использует и устаревшую доступную копию; при промахе возможна сеть.
      const response = await fetch(url, {
        cache: "force-cache",
        credentials: node?.crossOrigin === "use-credentials" ? "include" : "same-origin",
        signal: controller.signal,
      });
      if (!response.ok || response.type === "opaque") {
        log("image-source-error", "ответ страницы нельзя прочитать", { path: "page-fetch", status: response.status });
      } else {
        const bytes = await encode(await response.blob());
        if (!unchanged()) return {};
        log("image-source", "исходник прочитан со страницы", { path: "page-fetch" });
        return bytes;
      }
    } catch (error) {
      log("image-source-error", "не удалось прочитать исходник со страницы", { path: "page-fetch", name: error.name, code: error.message === "E_INLINE_SIZE" ? "E_INLINE_SIZE" : "" });
    } finally {
      clearTimeout(timer);
    }
    if (!unchanged()) return {};
    // Чужой origin без CORS даст SecurityError: защиту canvas не обходим.
    if (node?.tagName !== "IMG" || !node.complete || !node.naturalWidth || !node.naturalHeight
      || (node.currentSrc || node.src) !== url || node.naturalWidth * node.naturalHeight > 40_000_000) return {};
    let canvas;
    try {
      canvas = document.createElement("canvas");
      canvas.width = node.naturalWidth;
      canvas.height = node.naturalHeight;
      canvas.getContext("2d").drawImage(node, 0, 0);
      const blob = await new Promise((resolve, reject) => {
        try { canvas.toBlob(resolve, "image/png"); } catch (error) { reject(error); }
      });
      const bytes = await encode(blob);
      if (!unchanged()) return {};
      log("image-source", "использованы пиксели загруженного оригинала", { path: "loaded-image", width: canvas.width, height: canvas.height });
      return bytes;
    } catch (error) {
      log("image-source-error", "пиксели оригинала недоступны; пробуем загрузку расширением", { path: "loaded-image", name: error.name });
      return {};
    } finally {
      if (canvas) canvas.width = canvas.height = 0;
    }
  }

  globalThis.iltImageSource = { read };
})();
