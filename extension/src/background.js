"use strict";

// Фоновый воркер: модуль Chromium и классический скрипт Firefox.
const ext = globalThis.chrome ?? globalThis.browser;

const MENU_ID = "ilt-translate-image";
const MENU_TITLE = "Перевести изображение";
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
let pumping = false;
let menuChain = Promise.resolve();

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

function markError(job, message) {
  job.status = "error";
  job.error = message || "ошибка перевода";
  job.position = null;
  job.serverPosition = null;
  job.mime = null;
  job.blob = null;
  job.imageBase64 = null;
  job.base64Task = null;
  removeKey(pending, job.key);
  recomputePositions();
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

async function downloadImage(imageUrl) {
  if (isBlobUrl(imageUrl)) throw new Error("нельзя скачать изображение");
  let response;
  try {
    response = await fetch(imageUrl);
  } catch (_) {
    throw new Error("нельзя скачать изображение");
  }
  if (!response || !response.ok) throw new Error("нельзя скачать изображение");
  return response.blob();
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
  if (typeof data.progress === "number" && Number.isFinite(data.progress)) {
    job.progress = Math.max(0, Math.min(100, Math.round(data.progress)));
  }
  if (data.status !== "queued" && data.status !== "running") return;
  job.status = data.status;
  if (typeof data.position === "number" && Number.isFinite(data.position)) {
    job.serverPosition = data.position;
  }
  recomputePositions();
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
  if (isBlobUrl(job.imageUrl)) {
    markError(job, "нельзя скачать изображение");
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
  let imageBlob;
  try {
    imageBlob = await downloadImage(job.imageUrl);
  } catch (_) {
    markError(job, "нельзя скачать изображение");
    return;
  }
  let remoteId;
  try {
    remoteId = await postTranslate(settings.serverUrl, settings.token, imageBlob, job);
  } catch (err) {
    markError(job, toPipelineError(err));
    return;
  }
  job.remoteId = remoteId;
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
  job.blob = result.blob;
  job.mime = result.mime || "image/png";
  job.imageBase64 = null;
  job.base64Task = null;
  job.error = null;
  job.status = "done";
  job.position = null;
  job.serverPosition = null;
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

async function handleTranslateUrl(message) {
  if (!message || typeof message.imageUrl !== "string" || !message.imageUrl || typeof message.pageUrl !== "string" || !message.pageUrl) {
    return errorPayload("не указан адрес");
  }
  const reserved = reserveJob(message.pageUrl, message.imageUrl, message.force === true);
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

function onRuntimeMessage(message, _sender, sendResponse) {
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
  if (message.type === TYPE_TRANSLATE_URL) task = handleTranslateUrl(message);
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
  const createItem = () => callExt(ext.contextMenus.create.bind(ext.contextMenus), {
    id: MENU_ID,
    title: MENU_TITLE,
    contexts: ["image"],
  }).catch(() => {});
  if (typeof ext.contextMenus.removeAll !== "function") return createItem();
  return callExt(ext.contextMenus.removeAll.bind(ext.contextMenus)).then(createItem, createItem);
}

function ensureContextMenu() {
  menuChain = menuChain.then(rebuildContextMenu, rebuildContextMenu).catch(() => {});
}

function onContextMenuClick(info, tab) {
  if (!info || info.menuItemId !== MENU_ID) return;
  if (!info.srcUrl || !tab || !tab.id) return;
  if (!ext.tabs || typeof ext.tabs.sendMessage !== "function") return;
  callExt(ext.tabs.sendMessage.bind(ext.tabs), tab.id, {
    type: TYPE_TRANSLATE_IMAGE,
    imageUrl: info.srcUrl,
  }).catch(() => {});
}

function onRuntimeInstalled() {
  ensureContextMenu();
}

function installListeners() {
  if (!ext || !ext.runtime) return;
  if (ext.runtime.onMessage) ext.runtime.onMessage.addListener(onRuntimeMessage);
  if (ext.runtime.onInstalled) ext.runtime.onInstalled.addListener(onRuntimeInstalled);
  if (ext.contextMenus && ext.contextMenus.onClicked) {
    ext.contextMenus.onClicked.addListener(onContextMenuClick);
  }
  ensureContextMenu();
}

installListeners();
