"use strict";

// Фоновый воркер: модуль Chromium и классический скрипт Firefox.
const ext = globalThis.chrome ?? globalThis.browser;

const MENU_ID = "ilt-translate-image";
const MENU_TITLE = "Перевести изображение";
const SAVE_ID = "ilt-save-translation";
const SAVE_TITLE = "Сохранить перевод";
const DEFAULT_SERVER = "http://127.0.0.1:8765";
const MAX_CONCURRENT = 2;
const POLL_MS = 600;

const TYPE_TRANSLATE_URL = "translate-url";
const TYPE_TRANSLATE_ALL = "translate-all";
const TYPE_GET_STATUS = "get-status";
const TYPE_REQUEST_HOST = "requestHost";
const TYPE_TRANSLATE_IMAGE = "translate-image";
const TYPE_PLAY_CHIME = "play-chime";

const jobs = new Map();
const pending = [];
const activeKeys = [];
const pagePorts = new Set();
const LOG_LIMIT = 2000;
let pumping = false;
let menuChain = Promise.resolve();
let logToken = "";

// Один вызов API. Если вернулся thenable — берём его, иначе callback. Ответ один.
function callExt(fn, ...args) {
  return new Promise((resolve, reject) => {
    const state = { settled: false, preferPromise: false };
    const ok = (value) => {
      if (state.settled) return;
      state.settled = true;
      resolve(value);
    };
    const bad = (err) => {
      if (state.settled) return;
      state.settled = true;
      const message = err && err.message ? err.message : String(err || "ошибка расширения");
      reject(new Error(message));
    };
    let returned;
    try {
      returned = fn(...args, (value) => {
        const last = ext && ext.runtime ? ext.runtime.lastError : null;
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
    if (returned && typeof returned.then === "function") {
      state.preferPromise = true;
      returned.then(ok, bad);
    }
  });
}

function normalizeServerUrl(value) {
  const text = typeof value === "string" ? value.trim() : "";
  const url = text || DEFAULT_SERVER;
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

function pickLang(value, fallback) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof fallback === "string" && fallback.trim()) return fallback.trim();
  return "en";
}

function hasToken(token) {
  return typeof token === "string" && token.trim().length > 0;
}

function readSettings() {
  return callExt(ext.storage.local.get.bind(ext.storage.local), {
    serverUrl: DEFAULT_SERVER,
    token: "",
    targetLang: "ru",
  }).then((data) => {
    const stored = data && typeof data === "object" ? data : {};
    return {
      serverUrl: normalizeServerUrl(stored.serverUrl),
      token: typeof stored.token === "string" ? stored.token.trim() : "",
      targetLang: pickLang(stored.targetLang, "ru"),
    };
  });
}

function normalizePageUrl(pageUrl) {
  const raw = String(pageUrl);
  const hash = raw.indexOf("#");
  return hash === -1 ? raw : raw.slice(0, hash);
}

function cacheKey(pageUrl, imageUrl) {
  return normalizePageUrl(pageUrl) + "\n" + imageUrl;
}

function isBlobUrl(imageUrl) {
  return typeof imageUrl === "string" && /^blob:/i.test(imageUrl);
}

function fileNameFromUrl(imageUrl) {
  try {
    const base = new URL(imageUrl).pathname.split("/").filter(Boolean).pop() || "image";
    const clean = base.slice(0, 120);
    return clean || "image";
  } catch (_) {
    return "image";
  }
}

function normalizeMime(value) {
  if (typeof value !== "string") return "image/png";
  const raw = value.split(";")[0].trim().toLowerCase();
  return raw || "image/png";
}

function idlePayload() {
  return {
    ok: false,
    status: "idle",
    stage: "",
    progress: null,
    position: null,
    error: null,
    mime: null,
    imageBase64: null,
  };
}

function errorPayload(message) {
  return {
    ok: false,
    status: "error",
    stage: "",
    progress: null,
    position: null,
    error: message || "ошибка перевода",
    mime: null,
    imageBase64: null,
  };
}

function bytesToBase64(bytes) {
  // Меньше 10 тысяч аргументов, иначе apply переполняет стек.
  const chunkSize = 0x2000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const end = Math.min(offset + chunkSize, bytes.length);
    const chunk = new Array(end - offset);
    for (let i = 0; i < chunk.length; i += 1) chunk[i] = bytes[offset + i];
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  return bytesToBase64(new Uint8Array(buffer));
}

async function snapshot(job) {
  if (!job) return idlePayload();
  if (job.status === "error") {
    return {
      ok: false,
      status: "error",
      stage: job.stage || "",
      progress: typeof job.progress === "number" ? job.progress : null,
      position: null,
    error: job.error || "ошибка перевода",
    errorCode: job.errorCode || "",
    label: job.label || "",
    etaMs: typeof job.etaMs === "number" ? job.etaMs : null,
    elapsedMs: typeof job.elapsedMs === "number" ? job.elapsedMs : null,
    mime: null,
    imageBase64: null,
  };
}
  if (job.status === "done") {
    if (!job.blob) return errorPayload("ошибка перевода");
    if (!job.imageBase64) {
      if (!job.base64Task) job.base64Task = blobToBase64(job.blob);
      job.imageBase64 = await job.base64Task;
    }
    return {
      ok: true,
      status: "done",
      stage: job.stage || "",
      progress: typeof job.progress === "number" ? job.progress : null,
      position: null,
    error: null,
    errorCode: "",
    label: job.label || "",
    etaMs: null,
    elapsedMs: typeof job.elapsedMs === "number" ? job.elapsedMs : null,
    mime: job.mime || "image/png",
    imageBase64: job.imageBase64,
  };
}
  return {
    ok: true,
    status: job.status === "running" ? "running" : "queued",
    stage: job.stage || "",
    progress: typeof job.progress === "number" ? job.progress : null,
    position: typeof job.position === "number" ? job.position : null,
    error: null,
    errorCode: "",
    label: job.label || "",
    etaMs: typeof job.etaMs === "number" ? job.etaMs : null,
    elapsedMs: typeof job.elapsedMs === "number" ? job.elapsedMs : null,
    mime: null,
    imageBase64: null,
  };
}

function removeKey(list, key) {
  const index = list.indexOf(key);
  if (index !== -1) list.splice(index, 1);
}

function makeJob(key, pageUrl, imageUrl) {
  return {
    key: key,
    pageUrl: pageUrl,
    imageUrl: imageUrl,
    targetLang: "ru",
    status: "queued",
    stage: "",
    progress: null,
    position: null,
    serverPosition: null,
    error: null,
    mime: null,
    blob: null,
    imageBase64: null,
    base64Task: null,
    remoteId: "",
    langsReady: false,
    fresh: false,
    tabId: null,
    label: "",
    etaMs: null,
    elapsedMs: null,
    errorCode: "",
    suppliedBlob: null,
  };
}

// Локальная позиция: 1-based среди незавершённых, сначала уже запущенные.
function recomputePositions() {
  const seen = new Set();
  const ordered = [];
  const lists = [activeKeys, pending];
  for (let listIndex = 0; listIndex < lists.length; listIndex += 1) {
    const list = lists[listIndex];
    for (let i = 0; i < list.length; i += 1) {
      const key = list[i];
      if (seen.has(key)) continue;
      const job = jobs.get(key);
      if (!job) continue;
      if (job.status !== "queued" && job.status !== "running") continue;
      seen.add(key);
      ordered.push(job);
    }
  }
  for (let i = 0; i < ordered.length; i += 1) {
    const job = ordered[i];
    if (typeof job.serverPosition === "number") job.position = job.serverPosition;
    else job.position = i + 1;
  }
}

function markError(job, message, code) {
  job.status = "error";
  job.error = message || "ошибка перевода";
  job.errorCode = code || job.errorCode || "";
  job.position = null;
  job.serverPosition = null;
  job.mime = null;
  job.blob = null;
  job.imageBase64 = null;
  job.base64Task = null;
  removeKey(pending, job.key);
  recomputePositions();
  publishJob(job);
}

function reserveJob(pageUrl, imageUrl, force) {
  const key = cacheKey(pageUrl, imageUrl);
  const existing = jobs.get(key);
  if (!force && existing && existing.status === "done" && existing.blob) {
    return { job: existing, created: false };
  }
  if (existing && (existing.status === "queued" || existing.status === "running")) {
    return { job: existing, created: false };
  }
  removeKey(pending, key);
  removeKey(activeKeys, key);
  const job = makeJob(key, pageUrl, imageUrl);
  job.fresh = force === true;
  jobs.set(key, job);
  if (isBlobUrl(imageUrl)) {
    job.status = "error";
    job.error = "нельзя скачать изображение";
    job.langsReady = true;
    return { job: job, created: true };
  }
  pending.push(key);
  recomputePositions();
  return { job: job, created: true };
}

function pump() {
  if (pumping) return;
  pumping = true;
  try {
    while (activeKeys.length < MAX_CONCURRENT && pending.length > 0) {
      const key = pending[0];
      const job = jobs.get(key);
      if (!job || job.status === "error" || job.status === "done") {
        pending.shift();
        continue;
      }
      if (!job.langsReady) break;
      pending.shift();
      activeKeys.push(key);
      job.status = "running";
      recomputePositions();
      runJob(job);
    }
  } finally {
    pumping = false;
  }
}

function finishJob(job, run) {
  if (job.run !== run || jobs.get(job.key) !== job) {
    pump();
    return;
  }
  removeKey(activeKeys, job.key);
  recomputePositions();
  if (job.status === "done" || job.status === "error") {
    job.position = null;
    job.serverPosition = null;
  }
  pump();
}

function runJob(job) {
  const run = {};
  job.run = run;
  executeJob(job).then(
    () => finishJob(job, run),
    (err) => {
      if (job.run !== run || jobs.get(job.key) !== job) {
        pump();
        return;
      }
      if (job.status !== "done" && job.status !== "error") markError(job, toPipelineError(err));
      finishJob(job, run);
    }
  );
}

function isNetworkError(err) {
  if (!err || typeof err !== "object") return false;
  if (err.name === "TypeError" || err.name === "NetworkError") return true;
  const message = String(err.message || "");
  return message === "Failed to fetch"
    || /NetworkError|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|ECONNREFUSED|ENOTFOUND/i.test(message);
}

function toPipelineError(err) {
  if (isNetworkError(err)) return "сервер не найден";
  if (err && typeof err.message === "string" && err.message) return err.message;
  return "ошибка перевода";
}

function serverErrorText(value) {
  if (typeof value === "string" && value.trim()) return value;
  return "ошибка перевода";
}

function authHeaders(token) {
  return { Authorization: "Bearer " + token };
}

function apiUrl(serverUrl, path) {
  return serverUrl + path;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_) {
    return null;
  }
}

async function fetchApi(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    if (isNetworkError(err)) throw new Error("сервер не найден");
    throw err;
  }
  if (!response) throw new Error("сервер не найден");
  if (response.status === 401) throw new Error("ключ отозван");
  if (response.status === 429) throw new Error("очередь заполнена");
  if (!response.ok) {
    let message = "ошибка перевода";
    try {
      const data = await response.json();
      if (data && typeof data.error === "string" && data.error.trim()) message = data.error;
    } catch (_) {
      message = "ошибка перевода";
    }
    throw new Error(message);
  }
  return response;
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function publishJob(job) {
  if (!job) return;
  const message = {
    type: "job",
    pageUrl: job.pageUrl,
    imageUrl: job.imageUrl,
    status: job.status,
    stage: job.stage || "",
    progress: typeof job.progress === "number" ? job.progress : null,
    position: typeof job.position === "number" ? job.position : null,
    error: job.status === "error" ? job.error : null,
    errorCode: job.errorCode || "",
    label: job.label || "",
    etaMs: typeof job.etaMs === "number" ? job.etaMs : null,
    elapsedMs: typeof job.elapsedMs === "number" ? job.elapsedMs : null,
    ok: job.status !== "error",
  };
  if (job.status === "done" && job.imageBase64) {
    message.mime = job.mime || "image/png";
    message.imageBase64 = job.imageBase64;
  }
  for (const port of pagePorts) {
    try { port.postMessage(message); } catch (_) { /* порт уже закрыт */ }
  }
  refreshBadge(job.tabId);
  void persistActive();
}

function refreshBadge(tabId) {
  if (tabId == null || !ext.action?.setBadgeText) return;
  let active = 0;
  let failed = false;
  for (const job of jobs.values()) {
    if (job.tabId !== tabId) continue;
    if (job.status === "queued" || job.status === "running") active += 1;
    if (job.status === "error") failed = true;
  }
  const text = active ? String(Math.min(active, 99)) : (failed ? "!" : "");
  void callExt(ext.action.setBadgeText.bind(ext.action), { tabId: tabId, text: text }).catch(() => {});
}

async function persistActive() {
  if (!ext.storage?.session) return;
  const list = [];
  for (const job of jobs.values()) {
    if ((job.status !== "queued" && job.status !== "running") || !job.remoteId) continue;
    list.push({
      key: job.key,
      pageUrl: job.pageUrl,
      imageUrl: job.imageUrl,
      targetLang: job.targetLang,
      status: job.status,
      stage: job.stage,
      progress: job.progress,
      remoteId: job.remoteId,
      tabId: job.tabId || null,
    });
  }
  try {
    await callExt(ext.storage.session.set.bind(ext.storage.session), { iltJobs: list });
  } catch (_) { /* сессия недоступна */ }
}

function resultCacheUrl(imageUrl, lang) {
  const clean = String(imageUrl || "").split("#")[0];
  return "https://ilt-cache.local/" + encodeURIComponent(clean) + "?lang=" + encodeURIComponent(lang || "ru");
}

async function readResultCache(imageUrl, lang) {
  if (!globalThis.caches) return null;
  try {
    const cache = await caches.open("ilt-results");
    const hit = await cache.match(resultCacheUrl(imageUrl, lang));
    return hit ? hit.blob() : null;
  } catch (_) {
    return null;
  }
}

async function writeResultCache(imageUrl, lang, blob) {
  if (!globalThis.caches || !blob) return;
  try {
    const cache = await caches.open("ilt-results");
    await cache.put(resultCacheUrl(imageUrl, lang), new Response(blob, {
      headers: {
        "content-type": blob.type || "image/png",
        "x-ilt-size": String(blob.size || 0),
        "x-ilt-at": String(Date.now()),
      },
    }));
    const keys = await cache.keys();
    const items = [];
    let total = 0;
    for (let i = 0; i < keys.length; i += 1) {
      const response = await cache.match(keys[i]);
      const size = Number(response && response.headers.get("x-ilt-size")) || 0;
      const at = Number(response && response.headers.get("x-ilt-at")) || 0;
      total += size;
      items.push({ request: keys[i], size: size, at: at });
    }
    items.sort((a, b) => a.at - b.at);
    const limit = 300 * 1024 * 1024;
    while (total > limit && items.length) {
      const oldest = items.shift();
      total -= oldest.size;
      await cache.delete(oldest.request);
    }
  } catch (_) { /* кэш необязателен */ }
}

async function withReferer(imageUrl, pageUrl) {
  if (!ext.declarativeNetRequest?.updateSessionRules) return;
  let referer = pageUrl || "";
  try { referer = new URL(pageUrl).origin + "/"; } catch (_) {}
  let filter = imageUrl;
  try {
    const url = new URL(imageUrl);
    filter = url.origin + url.pathname;
  } catch (_) {}
  const condition = { urlFilter: filter, resourceTypes: ["xmlhttprequest", "other", "image"] };
  if (ext.runtime?.id) condition.initiatorDomains = [ext.runtime.id];
  await callExt(ext.declarativeNetRequest.updateSessionRules.bind(ext.declarativeNetRequest), {
    removeRuleIds: [7101],
    addRules: [{
      id: 7101,
      priority: 1,
      action: {
        type: "modifyHeaders",
        requestHeaders: [{ header: "Referer", operation: "set", value: referer }],
      },
      condition: condition,
    }],
  });
}

async function clearReferer() {
  if (!ext.declarativeNetRequest?.updateSessionRules) return;
  try {
    await callExt(ext.declarativeNetRequest.updateSessionRules.bind(ext.declarativeNetRequest), { removeRuleIds: [7101] });
  } catch (_) {}
}

function downloadError(status) {
  const error = new Error("нельзя скачать изображение");
  error.code = status ? "E_DOWNLOAD_" + status : "E_DOWNLOAD";
  return error;
}

async function downloadImage(imageUrl, pageUrl) {
  if (isBlobUrl(imageUrl) || /^data:/i.test(imageUrl)) throw downloadError(0);
  let response = null;
  try {
    response = await fetch(imageUrl, { credentials: "include", cache: "no-store" });
  } catch (_) {
    response = null;
  }
  if (response && (response.status === 401 || response.status === 403)) {
    try { await withReferer(imageUrl, pageUrl); } catch (_) {}
    try {
      response = await fetch(imageUrl, { credentials: "include", cache: "no-store" });
    } catch (_) {
      response = null;
    }
    await clearReferer();
  }
  if (!response || !response.ok) throw downloadError(response ? response.status : 0);
  return response.blob();
}

async function convertImage(blob) {
  const mime = normalizeMime(blob && blob.type);
  if (!blob || mime === "image/png" || mime === "image/jpeg" || mime === "image/webp") return blob;
  if (typeof OffscreenCanvas !== "function" || typeof createImageBitmap !== "function") return blob;
  const bitmap = await createImageBitmap(blob);
  const canvas = new OffscreenCanvas(Math.max(1, bitmap.width), Math.max(1, bitmap.height));
  canvas.getContext("2d").drawImage(bitmap, 0, 0);
  if (bitmap.close) bitmap.close();
  return canvas.convertToBlob({ type: "image/png" });
}

async function finishLocal(job) {
  job.status = "done";
  job.position = null;
  job.serverPosition = null;
  job.error = null;
  job.errorCode = "";
  const snap = await snapshot(job);
  publishJob(job);
  void writeResultCache(job.imageUrl, job.targetLang, job.blob);
  if (snap) void maybeChime();
  void persistActive();
}

async function maybeChime() {
  let data = {};
  try {
    data = await callExt(ext.storage.local.get.bind(ext.storage.local), { chimeOnReady: false, chimeId: "drop", chimeVolume: 50 });
  } catch (_) {
    return;
  }
  if (!data || data.chimeOnReady !== true) return;
  await playChimeMessage({ chimeId: data.chimeId, chimeVolume: data.chimeVolume });
}

function blobFromBase64(base64, mime) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime || "image/png" });
}

async function postTranslate(serverUrl, token, imageBlob, job) {
  const form = new FormData();
  form.append("file", imageBlob, fileNameFromUrl(job.imageUrl));
  form.append("target_lang", job.targetLang);
  if (job.fresh) form.append("fresh", "1");
  const response = await fetchApi(apiUrl(serverUrl, "/v1/translate"), {
    method: "POST",
    headers: authHeaders(token),
    body: form,
    cache: "no-store",
  });
  const data = await readJson(response);
  if (!data || data.job_id == null || data.job_id === "") throw new Error("ошибка перевода");
  return String(data.job_id);
}

function applyServerJob(job, data) {
  if (!data || typeof data !== "object") return;
  if (typeof data.stage === "string") job.stage = data.stage;
  if (typeof data.label === "string") job.label = data.label;
  if (typeof data.eta_ms === "number" && Number.isFinite(data.eta_ms)) job.etaMs = data.eta_ms;
  if (typeof data.elapsed_ms === "number" && Number.isFinite(data.elapsed_ms)) job.elapsedMs = data.elapsed_ms;
  if (typeof data.progress === "number" && Number.isFinite(data.progress)) {
    job.progress = Math.max(0, Math.min(100, Math.round(data.progress)));
  }
  if (data.status !== "queued" && data.status !== "running") return;
  job.status = data.status;
  if (typeof data.position === "number" && Number.isFinite(data.position)) {
    job.serverPosition = data.position;
  }
  recomputePositions();
  publishJob(job);
}

async function pollJob(serverUrl, token, job) {
  const url = apiUrl(serverUrl, "/v1/jobs/" + encodeURIComponent(job.remoteId));
  for (;;) {
    const response = await fetchApi(url, {
      method: "GET",
      headers: authHeaders(token),
      cache: "no-store",
    });
    const data = await readJson(response);
    applyServerJob(job, data);
    if (data && data.status === "done") {
      if (typeof data.stage === "string") job.stage = data.stage;
      job.status = "running";
      return;
    }
    if (data && data.status === "error") throw new Error(serverErrorText(data.error));
    if (!data || (data.status !== "queued" && data.status !== "running")) {
      throw new Error("ошибка перевода");
    }
    await delay(POLL_MS);
  }
}

async function fetchResult(serverUrl, token, remoteId) {
  const response = await fetchApi(apiUrl(serverUrl, "/v1/jobs/" + encodeURIComponent(remoteId) + "/result"), {
    method: "GET",
    headers: authHeaders(token),
    cache: "no-store",
  });
  const blob = await response.blob();
  const header = response.headers && response.headers.get ? response.headers.get("content-type") : "";
  return { blob: blob, mime: normalizeMime(header || blob.type || "image/png") };
}

async function deleteRemote(serverUrl, token, remoteId) {
  try {
    await fetch(apiUrl(serverUrl, "/v1/jobs/" + encodeURIComponent(remoteId)), {
      method: "DELETE",
      headers: authHeaders(token),
      cache: "no-store",
    });
  } catch (_) {
    // Удаление не отменяет уже скачанный результат.
  }
}

async function executeJob(job) {
  if ((isBlobUrl(job.imageUrl) || /^data:/i.test(job.imageUrl)) && !job.suppliedBlob) {
    markError(job, "нельзя скачать изображение", "E_DOWNLOAD");
    return;
  }
  let settings;
  try {
    settings = await readSettings();
  } catch (_) {
    markError(job, "ошибка перевода");
    return;
  }
  if (!hasToken(settings.token)) {
    markError(job, "нет ключа сопряжения");
    return;
  }
  logToken = settings.token;
  if (!job.fresh && !job.suppliedBlob) {
    const cached = await readResultCache(job.imageUrl, job.targetLang);
    if (cached) {
      job.blob = cached;
      job.mime = normalizeMime(cached.type || "image/png");
      job.stage = "cache";
      job.imageBase64 = null;
      job.base64Task = null;
      await finishLocal(job);
      return;
    }
  }
  let imageBlob = job.suppliedBlob || null;
  if (!imageBlob) {
    try {
      imageBlob = await downloadImage(job.imageUrl, job.pageUrl);
    } catch (err) {
      markError(job, "нельзя скачать изображение", err && err.code ? err.code : "E_DOWNLOAD");
      return;
    }
  }
  try {
    imageBlob = await convertImage(imageBlob);
  } catch (_) { /* отправим исходные байты */ }
  let remoteId;
  try {
    remoteId = await postTranslate(settings.serverUrl, settings.token, imageBlob, job);
  } catch (err) {
    markError(job, toPipelineError(err));
    return;
  }
  job.remoteId = remoteId;
  void persistActive();
  try {
    await pollJob(settings.serverUrl, settings.token, job);
  } catch (err) {
    markError(job, toPipelineError(err));
    return;
  }
  let result;
  try {
    result = await fetchResult(settings.serverUrl, settings.token, remoteId);
  } catch (err) {
    markError(job, toPipelineError(err));
    return;
  }
  try {
    job.blob = await convertImage(result.blob);
  } catch (_) {
    job.blob = result.blob;
  }
  job.mime = normalizeMime((job.blob && job.blob.type) || result.mime || "image/png");
  job.imageBase64 = null;
  job.base64Task = null;
  await finishLocal(job);
  await deleteRemote(settings.serverUrl, settings.token, remoteId);
}

async function prepareFresh(jobsToStart, targetLang) {
  let settings;
  try {
    settings = await readSettings();
  } catch (_) {
    for (let i = 0; i < jobsToStart.length; i += 1) markError(jobsToStart[i], "ошибка перевода");
    pump();
    return;
  }
  if (!hasToken(settings.token)) {
    for (let i = 0; i < jobsToStart.length; i += 1) {
      const job = jobsToStart[i];
      if (job.status === "queued" && !job.langsReady) markError(job, "нет ключа сопряжения");
    }
    pump();
    return;
  }
  const target = pickLang(targetLang, settings.targetLang);
  for (let i = 0; i < jobsToStart.length; i += 1) {
    const job = jobsToStart[i];
    if (job.status !== "queued" || job.langsReady) continue;
    job.targetLang = target;
    job.langsReady = true;
  }
  pump();
}

async function handleTranslateUrl(message, sender) {
  if (!message || typeof message.imageUrl !== "string" || !message.imageUrl || typeof message.pageUrl !== "string" || !message.pageUrl) {
    return errorPayload("не указан адрес");
  }
  const reserved = reserveJob(message.pageUrl, message.imageUrl, message.force === true);
  if (sender?.tab?.id != null) reserved.job.tabId = sender.tab.id;
  if (typeof message.imageBase64 === "string" && message.imageBase64) {
    try { reserved.job.suppliedBlob = blobFromBase64(message.imageBase64, message.imageMime); } catch (_) {}
  }
  if (!reserved.created || reserved.job.status === "error") return snapshot(reserved.job);
  await prepareFresh([reserved.job], message.targetLang);
  return snapshot(reserved.job);
}

async function handleTranslateAll(message) {
  if (!message || typeof message.pageUrl !== "string" || !message.pageUrl || !Array.isArray(message.urls)) {
    return { ok: false, count: 0 };
  }
  const fresh = [];
  // Счётчик: новые в очереди и уже запущенные. Готовый кэш сюда не входит.
  let count = 0;
  for (let i = 0; i < message.urls.length; i += 1) {
    const imageUrl = message.urls[i];
    if (typeof imageUrl !== "string" || !imageUrl) continue;
    const reserved = reserveJob(message.pageUrl, imageUrl);
    if (reserved.job.status === "queued" || reserved.job.status === "running") count += 1;
    if (reserved.created && reserved.job.status === "queued") fresh.push(reserved.job);
  }
  if (fresh.length) await prepareFresh(fresh, message.targetLang);
  return { ok: true, count: count };
}

async function handleGetStatus(message) {
  if (!message || typeof message.imageUrl !== "string" || !message.imageUrl || typeof message.pageUrl !== "string" || !message.pageUrl) {
    return idlePayload();
  }
  return snapshot(jobs.get(cacheKey(message.pageUrl, message.imageUrl)));
}

async function handleRequestHost(message) {
  if (!message || !Array.isArray(message.origins)) {
    return { ok: false, granted: false, error: "не указаны адреса" };
  }
  const origins = [];
  for (let i = 0; i < message.origins.length; i += 1) {
    const origin = message.origins[i];
    if (typeof origin === "string" && origin) origins.push(origin);
  }
  if (!origins.length) return { ok: false, granted: false, error: "не указаны адреса" };
  if (!ext.permissions || typeof ext.permissions.request !== "function") {
    return { ok: false, granted: false, error: "не удалось запросить доступ" };
  }
  try {
    const granted = await callExt(ext.permissions.request.bind(ext.permissions), { origins: origins });
    return { ok: true, granted: granted === true, error: null };
  } catch (err) {
    return {
      ok: false,
      granted: false,
      error: err && err.message ? String(err.message) : "не удалось запросить доступ",
    };
  }
}

async function playChimeMessage(message) {
  const chimeId = message && typeof message.chimeId === "string" ? message.chimeId : "drop";
  if (!ext.offscreen || typeof ext.offscreen.createDocument !== "function") return { ok: false };
  try {
    let open = false;
    if (typeof ext.offscreen.hasDocument === "function") {
      open = await callExt(ext.offscreen.hasDocument.bind(ext.offscreen));
    }
    if (!open) {
      await callExt(ext.offscreen.createDocument.bind(ext.offscreen), {
        url: "offscreen.html",
        reasons: ["AUDIO_PLAYBACK"],
        justification: "Короткий сигнал, когда перевод страницы закончился",
      });
    }
    return await callExt(ext.runtime.sendMessage.bind(ext.runtime), {
      type: "offscreen-play",
      chimeId,
      chimeVolume: message ? message.chimeVolume : undefined,
    });
  } catch (_) {
    return { ok: false };
  }
}

function setSaveVisible(visible) {
  if (!ext.contextMenus?.update) return;
  void callExt(ext.contextMenus.update.bind(ext.contextMenus), SAVE_ID, { visible: !!visible }).catch(() => {});
}

function scrubText(value, token) {
  let text = String(value ?? "");
  if (token && text.includes(token)) text = text.split(token).join("[redacted]");
  if (/^https?:/i.test(text)) {
    try {
      const url = new URL(text);
      url.search = "";
      url.hash = "";
      text = url.toString();
    } catch (_) {
      text = text.split("#")[0].split("?")[0];
    }
  }
  return text;
}

function scrubData(value, token) {
  if (typeof value === "string") return scrubText(value, token);
  if (Array.isArray(value)) return value.map((item) => scrubData(item, token));
  if (!value || typeof value !== "object") return value;
  const out = {};
  for (const key of Object.keys(value)) {
    if (/token|authorization/i.test(key)) continue;
    out[key] = scrubData(value[key], token);
  }
  return out;
}

let logMemory = [];

function writeLog(entries, sender) {
  const list = Array.isArray(entries) ? entries : [];
  const token = logToken;
  for (let i = 0; i < list.length; i += 1) {
    const entry = list[i] && typeof list[i] === "object" ? list[i] : { msg: String(list[i] || "") };
    logMemory.push({
      t: entry.t || Date.now(),
      lvl: entry.lvl || "info",
      src: entry.src || "bg",
      tab: sender?.tab?.id ?? entry.tab ?? null,
      ev: String(entry.ev || ""),
      msg: scrubText(entry.msg || "", token),
      data: scrubData(entry.data || {}, token),
    });
  }
  if (logMemory.length > LOG_LIMIT) logMemory = logMemory.slice(logMemory.length - LOG_LIMIT);
  if (!ext.storage?.local) return;
  void callExt(ext.storage.local.set.bind(ext.storage.local), { iltLog: logMemory }).catch(() => {});
}

async function logBundle() {
  let settings = {};
  try {
    settings = await callExt(ext.storage.local.get.bind(ext.storage.local), null);
  } catch (_) {}
  if (settings && typeof settings === "object") {
    settings = { ...settings };
    delete settings.token;
    delete settings.iltLog;
  }
  let health = null;
  try {
    const stored = await readSettings();
    logToken = stored.token;
    const response = await fetch(apiUrl(stored.serverUrl, "/v1/health"), { cache: "no-store" });
    health = await response.json();
  } catch (_) {
    health = null;
  }
  const jobsSummary = [];
  for (const job of jobs.values()) {
    jobsSummary.push({
      status: job.status,
      stage: job.stage,
      error: job.error,
      errorCode: job.errorCode,
      imageUrl: scrubText(job.imageUrl, logToken),
      pageUrl: scrubText(job.pageUrl, logToken),
    });
  }
  return {
    env: { ua: globalThis.navigator?.userAgent || "", time: new Date().toISOString() },
    settings: scrubData(settings, logToken),
    health: health,
    jobs: jobsSummary,
    entries: logMemory,
  };
}

function logFileName() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `ilt-extension-log-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}.json`;
}

async function exportLog(copy) {
  const bundle = await logBundle();
  const text = JSON.stringify(bundle, null, 2);
  if (copy) return { ok: true, text: text };
  if (!ext.downloads?.download) return { ok: false, text: text };
  await callExt(ext.downloads.download.bind(ext.downloads), {
    url: "data:application/json;charset=utf-8," + encodeURIComponent(text),
    filename: logFileName(),
    saveAs: true,
  });
  return { ok: true };
}

async function clearLog() {
  logMemory = [];
  if (ext.storage?.local) {
    try { await callExt(ext.storage.local.set.bind(ext.storage.local), { iltLog: [] }); } catch (_) {}
  }
  return { ok: true };
}

async function setVerbose(on) {
  if (ext.storage?.local) {
    try { await callExt(ext.storage.local.set.bind(ext.storage.local), { logVerbose: !!on }); } catch (_) {}
  }
  return { ok: true, on: !!on };
}

async function getVerbose() {
  if (!ext.storage?.local) return { on: false };
  try {
    const data = await callExt(ext.storage.local.get.bind(ext.storage.local), { logVerbose: false });
    return { on: data?.logVerbose === true };
  } catch (_) {
    return { on: false };
  }
}

async function saveKnown(message) {
  if (!message) return { ok: false, error: "нет перевода" };
  const job = jobs.get(cacheKey(message.pageUrl, message.imageUrl));
  if (!job || job.status !== "done" || !job.blob) return { ok: false, error: "нет перевода" };
  if (!job.imageBase64) {
    if (!job.base64Task) job.base64Task = blobToBase64(job.blob);
    job.imageBase64 = await job.base64Task;
  }
  const mime = job.mime || "image/png";
  const stem = fileNameFromUrl(job.imageUrl).replace(/\.[^.]+$/, "") || "image";
  const filename = `${stem}.${job.targetLang || "ru"}.png`;
  if (!ext.downloads || typeof ext.downloads.download !== "function") return { ok: false, error: "нет перевода" };
  await callExt(ext.downloads.download.bind(ext.downloads), {
    url: `data:${mime};base64,${job.imageBase64}`,
    filename: filename,
    saveAs: true,
  });
  return { ok: true };
}

function onRuntimeMessage(message, sender, sendResponse) {
  if (!message || typeof message !== "object" || typeof message.type !== "string") return undefined;
  if (message.type === TYPE_PLAY_CHIME) {
    playChimeMessage(message).then(
      (payload) => {
        try {
          sendResponse(payload && payload.ok ? { ok: true } : { ok: false });
        } catch (_) {}
      },
      () => {
        try {
          sendResponse({ ok: false });
        } catch (_) {}
      },
    );
    return true;
  }
  let task = null;
  if (message.type === "image-selected" && sender.tab?.id != null) {
    task = saveSelection(sender.tab.id, message).then(async (selection) => {
      const permitted = !selection.error && await selectionPermitted(selection);
      if (message.inline !== true && permitted) await handleTranslateUrl(selection);
      return { ok: true, permitted };
    });
  }
  else if (message.type === "get-selection") task = getSelection(message.tabId);
  else if (message.type === "open-panel") task = openPanel(message.tabId, message.windowId, message.active !== false).then(() => ({ ok: true }));
  else if (message.type === TYPE_TRANSLATE_URL) task = handleTranslateUrl(message, sender);
  else if (message.type === "context-target") {
    setSaveVisible(message.hasTranslation === true);
    sendResponse({ ok: true });
    return false;
  }
  else if (message.type === "save-result") task = saveKnown(message);
  else if (message.type === "log-write") { writeLog(message.entries, sender); sendResponse({ ok: true }); return false; }
  else if (message.type === "log-save") task = exportLog(false);
  else if (message.type === "log-copy") task = exportLog(true);
  else if (message.type === "log-clear") task = clearLog();
  else if (message.type === "log-verbose") task = setVerbose(message.on === true);
  else if (message.type === "log-verbose-get") task = getVerbose();
  else if (message.type === TYPE_TRANSLATE_ALL) task = handleTranslateAll(message);
  else if (message.type === TYPE_GET_STATUS) task = handleGetStatus(message);
  else if (message.type === TYPE_REQUEST_HOST) task = handleRequestHost(message);
  else return undefined;
  let replied = false;
  const reply = (payload) => {
    if (replied) return;
    replied = true;
    try {
      sendResponse(payload);
    } catch (_) {}
  };
  Promise.resolve(task).then(reply, (err) => {
    if (message.type === TYPE_TRANSLATE_ALL) reply({ ok: false, count: 0 });
    else if (message.type === TYPE_REQUEST_HOST) {
      reply({
        ok: false,
        granted: false,
        error: err && err.message ? String(err.message) : "не удалось запросить доступ",
      });
    } else reply(errorPayload(toPipelineError(err)));
  });
  return true;
}

function rebuildContextMenu() {
  if (!ext || !ext.contextMenus || typeof ext.contextMenus.create !== "function") return Promise.resolve();
  const createItems = () => Promise.all([
    callExt(ext.contextMenus.create.bind(ext.contextMenus), {
      id: MENU_ID,
      title: MENU_TITLE,
      contexts: ["image"],
    }).catch(() => {}),
    callExt(ext.contextMenus.create.bind(ext.contextMenus), {
      id: SAVE_ID,
      title: SAVE_TITLE,
      contexts: ["image"],
      visible: false,
    }).catch(() => {}),
  ]);
  if (typeof ext.contextMenus.removeAll !== "function") return createItems();
  return callExt(ext.contextMenus.removeAll.bind(ext.contextMenus)).then(createItems, createItems);
}

function ensureContextMenu() {
  menuChain = menuChain.then(rebuildContextMenu, rebuildContextMenu).catch(() => {});
}

const selections = new Map();

function selectionOrigins(selection, serverUrl) {
  const origins = new Set();
  for (const value of [selection.imageUrl, serverUrl]) {
    try {
      const url = new URL(value);
      if (url.protocol === "http:" || url.protocol === "https:") origins.add(url.origin + "/*");
    } catch (_) { /* адрес проверяется при загрузке */ }
  }
  return [...origins];
}

async function selectionPermitted(selection) {
  const settings = await readSettings();
  const origins = selectionOrigins(selection, settings.serverUrl);
  return !origins.length || await callExt(ext.permissions.contains.bind(ext.permissions), { origins });
}

async function saveSelection(tabId, message) {
  const selection = {
    imageUrl: String(message.imageUrl || ""),
    pageUrl: String(message.pageUrl || ""),
    error: String(message.error || ""),
  };
  selections.set(tabId, selection);
  if (ext.storage.session) {
    await callExt(ext.storage.session.set.bind(ext.storage.session), { ["selection:" + tabId]: selection });
  }
  return selection;
}

async function getSelection(tabId) {
  if (ext.storage.session) {
    const key = "selection:" + tabId;
    const data = await callExt(ext.storage.session.get.bind(ext.storage.session), key);
    return data[key] || null;
  }
  return selections.get(tabId) || null;
}

function openPanel() {
  return Promise.resolve();
}

function markPageError(tabId, message) {
  if (ext.action?.setBadgeText) void callExt(ext.action.setBadgeText.bind(ext.action), { tabId, text: "!" });
  if (ext.action?.setTitle) void callExt(ext.action.setTitle.bind(ext.action), {
    tabId,
    title: "Image Localization Tool: " + (message || "Нет доступа к странице"),
  });
}

async function saveTranslation(info, tab) {
  if (!info?.srcUrl || tab?.id == null) return;
  try {
    const response = await callExt(ext.tabs.sendMessage.bind(ext.tabs), tab.id,
      { type: "inline-save", srcUrl: info.srcUrl }, { frameId: info.frameId || 0 });
    if (!response?.ok) throw new Error(response?.error || "нет перевода");
    const job = jobs.get(cacheKey(response.pageUrl, response.imageUrl));
    if (!job || job.status !== "done" || !job.blob) throw new Error("нет перевода");
    if (!job.imageBase64) {
      if (!job.base64Task) job.base64Task = blobToBase64(job.blob);
      job.imageBase64 = await job.base64Task;
    }
    const mime = job.mime || "image/png";
    const stem = fileNameFromUrl(job.imageUrl).replace(/\.[^.]+$/, "") || "image";
    const filename = `${stem}.${job.targetLang || "ru"}.png`;
    if (!ext.downloads || typeof ext.downloads.download !== "function") throw new Error("нет перевода");
    await callExt(ext.downloads.download.bind(ext.downloads), {
      url: `data:${mime};base64,${job.imageBase64}`,
      filename,
      saveAs: true,
    });
  } catch (error) {
    markPageError(tab.id, error.message || "нет перевода");
  }
}

function onContextMenuClick(info, tab) {
  if (!info) return;
  if (info.menuItemId === SAVE_ID) {
    void saveTranslation(info, tab);
    return;
  }
  if (info.menuItemId !== MENU_ID) return;
  if (!info.srcUrl || tab?.id == null) return;
  const message = { imageUrl: info.srcUrl, pageUrl: info.frameUrl || info.pageUrl || tab.url };
  void saveSelection(tab.id, message).then(async (selection) => {
    const permitted = await selectionPermitted(selection);
    const response = await callExt(ext.tabs.sendMessage.bind(ext.tabs), tab.id,
      { type: "translate-inline", ...selection, permitted: !!permitted }, { frameId: info.frameId || 0 });
    if (!response?.ok) throw new Error(response?.error || "Обновите страницу и повторите выбор изображения");
    if (ext.action?.setBadgeText) void callExt(ext.action.setBadgeText.bind(ext.action), { tabId: tab.id, text: "" });
    if (ext.action?.setTitle) void callExt(ext.action.setTitle.bind(ext.action), { tabId: tab.id, title: "Image Localization Tool" });
  }).catch((error) => {
    markPageError(tab.id, error.message);
  });
}

function onRuntimeInstalled() {
  ensureContextMenu();
  if (ext.storage?.local?.remove) {
    void callExt(ext.storage.local.remove.bind(ext.storage.local), ["interactionMode", "autoSites"]).catch(() => {});
  }
}

function installListeners() {
  if (!ext || !ext.runtime) return;
  if (ext.runtime.onMessage) ext.runtime.onMessage.addListener(onRuntimeMessage);
  if (ext.runtime.onInstalled) ext.runtime.onInstalled.addListener(onRuntimeInstalled);
  if (ext.contextMenus && ext.contextMenus.onClicked) {
    ext.contextMenus.onClicked.addListener(onContextMenuClick);
  }
  if (ext.tabs?.onRemoved) ext.tabs.onRemoved.addListener((tabId) => {
    selections.delete(tabId);
    if (ext.storage.session) void callExt(ext.storage.session.remove.bind(ext.storage.session), "selection:" + tabId).catch(() => {});
  });
  if (ext.runtime.onConnect) ext.runtime.onConnect.addListener((port) => {
    if (!port || port.name !== "ilt-page") return;
    pagePorts.add(port);
    if (port.onDisconnect) port.onDisconnect.addListener(() => pagePorts.delete(port));
  });
  if (ext.commands?.onCommand) ext.commands.onCommand.addListener((command) => {
    if (command !== "translate-hovered" || !ext.tabs?.query) return;
    void callExt(ext.tabs.query.bind(ext.tabs), { active: true, currentWindow: true }).then((tabs) => {
      const tab = tabs && tabs[0];
      if (!tab || tab.id == null) return null;
      return callExt(ext.tabs.sendMessage.bind(ext.tabs), tab.id, { type: "translate-hovered" });
    }).catch(() => {});
  });
  if (typeof addEventListener === "function") {
    addEventListener("error", (event) => {
      writeLog([{ lvl: "error", src: "bg", ev: "error", msg: event && event.message ? event.message : "error" }], null);
    });
    addEventListener("unhandledrejection", (event) => {
      const reason = event && event.reason;
      writeLog([{ lvl: "error", src: "bg", ev: "unhandledrejection", msg: reason && reason.message ? reason.message : String(reason || "") }], null);
    });
  }
  ensureContextMenu();
  void resumeStoredJobs();
}

async function resumeStoredJobs() {
  if (!ext.storage?.session) return;
  let data = {};
  try {
    data = await callExt(ext.storage.session.get.bind(ext.storage.session), "iltJobs");
  } catch (_) {
    return;
  }
  const list = data && Array.isArray(data.iltJobs) ? data.iltJobs : [];
  for (let i = 0; i < list.length; i += 1) {
    const meta = list[i];
    if (!meta?.remoteId || jobs.has(meta.key)) continue;
    const job = makeJob(meta.key, meta.pageUrl, meta.imageUrl);
    job.targetLang = meta.targetLang || "ru";
    job.remoteId = meta.remoteId;
    job.status = "running";
    job.langsReady = true;
    job.tabId = meta.tabId;
    jobs.set(job.key, job);
    activeKeys.push(job.key);
    void resumeRemote(job);
  }
}

async function resumeRemote(job) {
  let settings;
  try {
    settings = await readSettings();
  } catch (_) {
    markError(job, "ошибка перевода");
    return;
  }
  if (!hasToken(settings.token)) {
    markError(job, "нет ключа сопряжения");
    return;
  }
  try {
    await pollJob(settings.serverUrl, settings.token, job);
    const result = await fetchResult(settings.serverUrl, settings.token, job.remoteId);
    job.blob = result.blob;
    job.mime = result.mime || "image/png";
    job.imageBase64 = null;
    job.base64Task = null;
    await finishLocal(job);
    await deleteRemote(settings.serverUrl, settings.token, job.remoteId);
  } catch (err) {
    markError(job, toPipelineError(err), err && err.code ? err.code : "");
  }
}

installListeners();

globalThis.iltOnContextMenuClick = onContextMenuClick;
