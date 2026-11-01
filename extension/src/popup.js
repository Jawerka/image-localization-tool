"use strict";

const ext = globalThis.chrome ?? globalThis.browser;

function call(fn, ...args) {
  return new Promise((resolve, reject) => {
    let done = false;
    const ok = (value) => { if (!done) { done = true; resolve(value); } };
    const fail = (err) => { if (!done) { done = true; reject(err instanceof Error ? err : new Error(String(err))); } };
    let result;
    try { result = fn(...args, (value) => (ext.runtime.lastError ? fail(ext.runtime.lastError) : ok(value))); }
    catch (_) {
      try { result = fn(...args); } catch (err) { fail(err); return; }
    }
    if (result && typeof result.then === "function") result.then(ok, fail);
  });
}

function storageGet(keys) { return call(ext.storage.local.get.bind(ext.storage.local), keys); }
function storageSet(items) { return call(ext.storage.local.set.bind(ext.storage.local), items); }

const targetEl = document.getElementById("target");
const siteEl = document.getElementById("site-button");
const statusEl = document.getElementById("status");
const dotEl = document.getElementById("dot");
const linkEl = document.getElementById("link");
const countEl = document.getElementById("count");
const logsEl = document.getElementById("save-logs");
let host = "";
let tab = null;
let originals = false;

function pickLang(value) {
  return value === "en" || value === "uk" ? value : "ru";
}

function setStatus(text) { statusEl.textContent = text || ""; }

function applyTheme(value) {
  const theme = value === "light" || value === "dark" ? value : "system";
  document.documentElement.dataset.theme = theme;
}

async function activeTab() {
  const tabs = await call(ext.tabs.query.bind(ext.tabs), { active: true, currentWindow: true });
  return tabs && tabs[0];
}

function hostname(value) {
  try {
    const url = new URL(value || "");
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.hostname;
  } catch (_) { return ""; }
}

async function paintLink() {
  const data = await storageGet({ serverUrl: "http://127.0.0.1:8765", token: "" });
  const paired = typeof data.token === "string" && data.token.trim().length > 0;
  document.getElementById("connect").hidden = paired;
  if (!paired) {
    dotEl.className = "dot bad";
    linkEl.textContent = "Нет связи";
    return;
  }
  try {
    const server = String(data.serverUrl || "http://127.0.0.1:8765").replace(/\/$/, "");
    const response = await fetch(server + "/v1/health");
    const body = await response.json();
    const ok = response.ok && body && body.ready === true;
    dotEl.className = ok ? "dot ok" : "dot bad";
    linkEl.textContent = ok ? "Связь есть" : "Сервер не готов";
  } catch (_) {
    dotEl.className = "dot bad";
    linkEl.textContent = "Нет связи";
  }
}

async function paintPage() {
  if (!tab || tab.id == null) {
    countEl.textContent = "Переводов на вкладке: 0";
    return;
  }
  try {
    const summary = await call(ext.tabs.sendMessage.bind(ext.tabs), tab.id, { type: "page-summary" });
    const count = summary && summary.count ? summary.count : 0;
    countEl.textContent = "Переводов на вкладке: " + count;
    logsEl.hidden = !(summary && summary.errors);
  } catch (_) {
    countEl.textContent = "Переводов на вкладке: 0";
  }
}

targetEl.addEventListener("change", () => {
  storageSet({ targetLang: pickLang(targetEl.value) }).catch(() => {});
});

siteEl.addEventListener("change", () => {
  if (!host) return;
  storageGet({ hoverDisabledSites: [] }).then((data) => {
    const list = Array.isArray(data.hoverDisabledSites) ? data.hoverDisabledSites.filter((item) => item !== host) : [];
    if (!siteEl.checked) list.push(host);
    return storageSet({ hoverDisabledSites: list });
  }).catch(() => setStatus("Не удалось сохранить"));
});

document.getElementById("show-originals").addEventListener("click", () => {
  if (!tab) return;
  originals = !originals;
  call(ext.tabs.sendMessage.bind(ext.tabs), tab.id, { type: "show-originals", on: originals })
    .then(() => { document.getElementById("show-originals").textContent = originals ? "Показать все переводы" : "Показать все оригиналы"; })
    .catch(() => setStatus("нет доступа к странице"));
});

document.getElementById("remove-all").addEventListener("click", () => {
  if (!tab) return;
  call(ext.tabs.sendMessage.bind(ext.tabs), tab.id, { type: "remove-all" })
    .then(() => paintPage())
    .catch(() => setStatus("нет доступа к странице"));
});

document.getElementById("select-image").addEventListener("click", () => {
  if (!tab) { setStatus("нет активной вкладки"); return; }
  call(ext.tabs.sendMessage.bind(ext.tabs), tab.id, { type: "select-image" })
    .then(() => window.close())
    .catch(() => setStatus("Нет доступа к странице. Обновите её и проверьте разрешения расширения"));
});

function openOptions() {
  call(ext.runtime.openOptionsPage.bind(ext.runtime)).catch(() => {});
}
document.getElementById("open-options").addEventListener("click", openOptions);
document.getElementById("open-options-connect").addEventListener("click", (event) => {
  event.preventDefault();
  openOptions();
});

logsEl.addEventListener("click", () => {
  globalThis.iltLog?.save().catch(() => setStatus("Не удалось сохранить логи"));
});

async function init() {
  const data = await storageGet({ targetLang: "ru", hoverDisabledSites: [], token: "", theme: "system" }).catch(() => ({}));
  applyTheme(data.theme);
  targetEl.value = pickLang(data.targetLang);
  tab = await activeTab().catch(() => null);
  host = hostname(tab && tab.url);
  const disabled = Array.isArray(data.hoverDisabledSites) ? data.hoverDisabledSites : [];
  siteEl.checked = !!host && !disabled.includes(host);
  siteEl.disabled = !host;
  if (!host) setStatus("нет активной вкладки");
  await paintLink();
  await paintPage();
}

init();
