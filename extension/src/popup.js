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

const sourceEl = document.getElementById("source");
const targetEl = document.getElementById("target");
const autoEl = document.getElementById("auto");
const statusEl = document.getElementById("status");

function pickLang(value, fallback) {
  return value === "en" || value === "ru" ? value : fallback;
}

function setStatus(text) {
  statusEl.textContent = text;
}

function httpHost(tab) {
  if (!tab || !tab.url) return "";
  try {
    const url = new URL(tab.url);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.hostname;
  } catch (_) {
    return "";
  }
}

function queryActiveTab() {
  return call(ext.tabs.query.bind(ext.tabs), { active: true, currentWindow: true });
}

let host = "";
let sitesWrite = Promise.resolve();

sourceEl.addEventListener("change", () => {
  storageSet({ sourceLang: pickLang(sourceEl.value, "en") }).catch(() => {});
});

targetEl.addEventListener("change", () => {
  storageSet({ targetLang: pickLang(targetEl.value, "ru") }).catch(() => {});
});

autoEl.addEventListener("change", () => {
  if (!host) return;
  const enabled = autoEl.checked;
  sitesWrite = sitesWrite
    .then(async () => {
      const data = await storageGet("autoSites");
      const prev = data && data.autoSites && typeof data.autoSites === "object" ? data.autoSites : {};
      const sites = { ...prev };
      sites[host] = enabled;
      await storageSet({ autoSites: sites });
    })
    .catch(() => {});
});

document.getElementById("open-options").addEventListener("click", () => {
  call(ext.runtime.openOptionsPage.bind(ext.runtime)).catch(() => {});
});

document.getElementById("translate-all").addEventListener("click", () => {
  const sourceLang = pickLang(sourceEl.value, "en");
  const targetLang = pickLang(targetEl.value, "ru");
  translatePage(sourceLang, targetLang);
});

async function translatePage(sourceLang, targetLang) {
  try {
    await storageSet({ sourceLang, targetLang });
  } catch (_) {}
  try {
    const tabs = await queryActiveTab();
    const tab = tabs && tabs[0];
    if (!tab || tab.id == null) {
      setStatus("нет доступа к странице");
      return;
    }
    await call(ext.tabs.sendMessage.bind(ext.tabs), tab.id, {
      type: "translate-all-page",
      sourceLang,
      targetLang,
    });
    setStatus("запущено");
  } catch (_) {
    setStatus("нет доступа к странице");
  }
}

async function init() {
  autoEl.disabled = true;
  let data = {};
  try {
    data = (await storageGet(["sourceLang", "targetLang", "autoSites"])) || {};
    sourceEl.value = data.sourceLang === "ru" ? "ru" : "en";
    targetEl.value = data.targetLang === "en" ? "en" : "ru";
  } catch (_) {}
  let tab = null;
  try {
    const tabs = await queryActiveTab();
    tab = tabs && tabs[0];
  } catch (_) {}
  host = httpHost(tab);
  if (!host) {
    setStatus("нет активной вкладки");
    return;
  }
  const sites = data.autoSites && typeof data.autoSites === "object" ? data.autoSites : {};
  autoEl.checked = sites[host] === true;
  autoEl.disabled = false;
}

init();
