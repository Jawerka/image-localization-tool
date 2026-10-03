"use strict";

const ext = globalThis.chrome ?? globalThis.browser;

/** chrome — callback и lastError, browser — Promise. */
function call(fn, ...args) {
  return new Promise((resolve, reject) => {
    let done = false;
    const ok = (value) => {
      if (done) return;
      done = true;
      resolve(value);
    };
    const fail = (err) => {
      if (done) return;
      done = true;
      const message = err && err.message ? err.message : String(err);
      reject(new Error(message));
    };
    const fromCallback = (value) => {
      const lastError = ext.runtime && ext.runtime.lastError;
      if (lastError) fail(lastError);
      else ok(value);
    };
    let result;
    try {
      result = fn(...args, fromCallback);
    } catch (_) {
      try {
        result = fn(...args);
      } catch (err) {
        fail(err);
        return;
      }
    }
    if (result && typeof result.then === "function") result.then(ok, fail);
  });
}

function storageGet(keys) {
  return call(ext.storage.local.get.bind(ext.storage.local), keys);
}

function storageSet(items) {
  return call(ext.storage.local.set.bind(ext.storage.local), items);
}

const serverEl = document.getElementById("server-url");
const codeEl = document.getElementById("pair-code");
const statusEl = document.getElementById("status");
const DEFAULT_SERVER = "http://127.0.0.1:8765";

function setStatus(text) {
  statusEl.textContent = text;
}

function normalizeServerUrl(value) {
  const text = String(value ?? "").trim();
  const url = text || DEFAULT_SERVER;
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

function httpFailure(res) {
  if (res.status === 401) return "ключ отозван";
  if (res.status === 429) return "очередь заполнена";
  if (!res.ok) return "ошибка сервера " + res.status;
  return "";
}

/** Вызов permissions.request синхронно, пока жив жест пользователя. */
function askOrigin(serverUrl) {
  try {
    const pattern = new URL(serverUrl).origin + "/*";
    if (!ext.permissions || typeof ext.permissions.request !== "function") {
      return Promise.resolve();
    }
    return call(ext.permissions.request.bind(ext.permissions), {
      origins: [pattern],
    }).catch(() => {});
  } catch (_) {
    return Promise.resolve();
  }
}

document.getElementById("pair").addEventListener("click", () => {
  const serverUrl = normalizeServerUrl(serverEl.value);
  serverEl.value = serverUrl;
  const perm = askOrigin(serverUrl);
  const code = codeEl.value.trim();
  pair(serverUrl, code, perm);
});

document.getElementById("check").addEventListener("click", () => {
  const serverUrl = normalizeServerUrl(serverEl.value);
  serverEl.value = serverUrl;
  const perm = askOrigin(serverUrl);
  check(serverUrl, perm);
});

async function pair(serverUrl, code, perm) {
  // Жест уже вызвал permissions.request; ответ сервера не ждёт диалог.
  void perm;
  try {
    await storageSet({ serverUrl });
  } catch (_) {}
  let res;
  try {
    res = await fetch(serverUrl + "/v1/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
  } catch (_) {
    setStatus("сервер не найден");
    return;
  }
  const failure = httpFailure(res);
  if (failure) {
    setStatus(failure);
    return;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (_) {}
  if (!data || typeof data.token !== "string") {
    setStatus("ошибка сервера " + res.status);
    return;
  }
  try {
    await storageSet({ token: data.token });
  } catch (_) {
    setStatus("ошибка сервера " + res.status);
    return;
  }
  setStatus("сопряжено");
}

async function check(serverUrl, perm) {
  // Жест уже вызвал permissions.request; проверка связи не ждёт диалог.
  void perm;
  try {
    await storageSet({ serverUrl });
  } catch (_) {}
  let res;
  try {
    res = await fetch(serverUrl + "/v1/health");
  } catch (_) {
    setStatus("сервер не найден");
    return;
  }
  const failure = httpFailure(res);
  if (failure) {
    setStatus(failure);
    return;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (_) {}
  if (data && data.ready === true) {
    setStatus("связь есть");
    return;
  }
  setStatus("сервер не готов");
}

storageGet("serverUrl")
  .then((data) => {
    if (data && typeof data.serverUrl === "string" && data.serverUrl) {
      serverEl.value = data.serverUrl;
    }
  })
  .catch(() => {});
