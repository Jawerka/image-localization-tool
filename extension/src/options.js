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

let statusGen = 0;

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

document.getElementById("pair").addEventListener("click", () => {
  const serverUrl = normalizeServerUrl(serverEl.value);
  serverEl.value = serverUrl;
  const code = codeEl.value.trim();
  pair(serverUrl, code);
});

document.getElementById("check").addEventListener("click", () => {
  const serverUrl = normalizeServerUrl(serverEl.value);
  serverEl.value = serverUrl;
  check(serverUrl);
});

async function pair(serverUrl, code) {
  const gen = ++statusGen;
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
  if (gen !== statusGen) return;
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
  if (gen === statusGen) setStatus("сопряжено");
}

async function check(serverUrl) {
  const gen = ++statusGen;
  try {
    await storageSet({ serverUrl });
  } catch (_) {}
  let res;
  try {
    res = await fetch(serverUrl + "/v1/health");
  } catch (_) {
    if (gen === statusGen) setStatus("сервер не найден");
    return;
  }
  if (gen !== statusGen) return;
  const failure = httpFailure(res);
  if (failure) {
    setStatus(failure);
    return;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (_) {}
  if (gen !== statusGen) return;
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

const chimeRoot = document.getElementById("chimes");
const chimeApi = globalThis.iltChime;
const volumeEl = document.getElementById("chime-volume");
const volumeValueEl = document.getElementById("chime-volume-value");

function paintVolume(value) {
  const n = chimeApi ? chimeApi.clampVolume(value) : 50;
  if (volumeEl) volumeEl.value = String(n);
  if (volumeValueEl) volumeValueEl.textContent = n + "%";
  return n;
}

function currentVolume() {
  return paintVolume(volumeEl ? volumeEl.value : 50);
}

function bindChimes() {
  if (!chimeRoot || !chimeApi) return;
  const list = chimeApi.list;
  for (let i = 0; i < list.length; i++) {
    const item = list[i];
    const row = document.createElement("div");
    row.className = "chime";
    const label = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "chime";
    radio.value = item.id;
    radio.addEventListener("change", () => {
      if (!radio.checked) return;
      storageSet({ chimeId: item.id }).catch(() => {});
    });
    label.appendChild(radio);
    label.appendChild(document.createTextNode(item.title));
    row.appendChild(label);
    if (item.id !== chimeApi.offId) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Прослушать";
      button.addEventListener("click", () => {
        const volume = currentVolume();
        storageSet({ chimeVolume: volume }).catch(() => {});
        chimeApi.play(item.id, volume).catch(() => {});
      });
      row.appendChild(button);
    }
    chimeRoot.appendChild(row);
  }
  if (volumeEl) {
    volumeEl.addEventListener("input", () => {
      const volume = currentVolume();
      storageSet({ chimeVolume: volume }).catch(() => {});
    });
  }
  storageGet(["chimeId", "chimeVolume"])
    .then((data) => {
      const stored = data && typeof data.chimeId === "string" ? data.chimeId : "";
      const id = chimeApi.known(stored) ? stored : chimeApi.defaultId;
      const radio = chimeRoot.querySelector('input[value="' + id + '"]');
      if (radio) radio.checked = true;
      paintVolume(data ? data.chimeVolume : chimeApi.defaultVolume);
    })
    .catch(() => {});
}

bindChimes();

const disabledSitesEl = document.getElementById("hover-disabled-sites");
const buttonEl = document.getElementById("button-enabled");
const delayEl = document.getElementById("hover-delay");
const minEl = document.getElementById("hover-min");
const themeEl = document.getElementById("theme");
const chimeOnEl = document.getElementById("chime-on");
const cells = document.getElementById("pair-cells");

function applyTheme(value) {
  const theme = value === "light" || value === "dark" ? value : "system";
  document.documentElement.dataset.theme = theme;
}

function saveSites() {
  const hoverDisabledSites = [...new Set(disabledSitesEl.value.split(/\s+/).map((host) => host.trim().toLowerCase()).filter(Boolean))];
  storageSet({ hoverDisabledSites }).catch(() => setStatus("Не удалось сохранить исключения"));
}

if (cells && codeEl) {
  for (let i = 0; i < 6; i += 1) {
    const input = document.createElement("input");
    input.maxLength = 1;
    input.inputMode = "numeric";
    input.addEventListener("input", () => {
      const chars = [...cells.querySelectorAll("input")].map((item) => item.value).join("");
      codeEl.value = chars;
      if (input.value && input.nextElementSibling) input.nextElementSibling.focus();
    });
    cells.appendChild(input);
  }
  codeEl.addEventListener("input", () => {
    const digits = codeEl.value.replace(/\D/g, "").slice(0, 6);
    codeEl.value = digits;
    const inputs = [...cells.querySelectorAll("input")];
    for (let i = 0; i < inputs.length; i += 1) inputs[i].value = digits[i] || "";
  });
}

disabledSitesEl.addEventListener("change", saveSites);
buttonEl.addEventListener("change", () => {
  storageSet({ buttonEnabled: buttonEl.checked }).catch(() => setStatus("Не удалось сохранить"));
});
delayEl.addEventListener("change", () => {
  storageSet({ hoverDelayMs: Number(delayEl.value) || 220 }).catch(() => {});
});
minEl.addEventListener("change", () => {
  storageSet({ hoverMinLong: Number(minEl.value) || 160 }).catch(() => {});
});
themeEl.addEventListener("change", () => {
  applyTheme(themeEl.value);
  storageSet({ theme: themeEl.value }).catch(() => {});
});
chimeOnEl.addEventListener("change", () => {
  storageSet({ chimeOnReady: chimeOnEl.checked }).catch(() => {});
});

storageGet(["hoverDisabledSites", "buttonEnabled", "hoverDelayMs", "hoverMinLong", "theme", "chimeOnReady"]).then((data) => {
  disabledSitesEl.value = Array.isArray(data.hoverDisabledSites) ? data.hoverDisabledSites.join("\n") : "";
  buttonEl.checked = data.buttonEnabled !== false;
  if (data.hoverDelayMs) delayEl.value = String(data.hoverDelayMs);
  if (data.hoverMinLong) minEl.value = String(data.hoverMinLong);
  themeEl.value = data.theme === "light" || data.theme === "dark" ? data.theme : "system";
  applyTheme(themeEl.value);
  chimeOnEl.checked = data.chimeOnReady === true;
}).catch(() => {});

const verboseEl = document.getElementById("log-verbose");
if (verboseEl && globalThis.iltLog) {
  globalThis.iltLog.verbose().then((value) => { verboseEl.checked = !!(value && value.on); }).catch(() => {});
  verboseEl.addEventListener("change", () => { globalThis.iltLog.setVerbose(verboseEl.checked); });
  document.getElementById("save-logs").addEventListener("click", () => { globalThis.iltLog.save(); });
  document.getElementById("copy-logs").addEventListener("click", () => {
    globalThis.iltLog.copy().then((value) => {
      if (value && value.text && navigator.clipboard) return navigator.clipboard.writeText(value.text);
      return null;
    }).then(() => setStatus("скопировано"), () => setStatus("не удалось скопировать"));
  });
  document.getElementById("clear-logs").addEventListener("click", () => { globalThis.iltLog.clear(); });
}

storageGet("serverUrl").then((data) => {
  const serverUrl = data && typeof data.serverUrl === "string" && data.serverUrl ? data.serverUrl : DEFAULT_SERVER;
  check(serverUrl);
}).catch(() => {});
