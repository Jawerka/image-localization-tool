/* Запросы к локальному API. Токен в хранилище страницы не пишется. */

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request(method, url, body) {
  const options = {
    method,
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new ApiError("Нет связи с программой", 0, null);
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = { raw: text };
    }
  }
  if (!response.ok) {
    const message = (data && (data.error || data.message)) || response.statusText || "Ошибка запроса";
    throw new ApiError(String(message), response.status, data);
  }
  return data;
}

export function session(token) {
  return request("POST", "/api/session", { token });
}

export function bootstrap() {
  return request("GET", "/api/bootstrap");
}

export function putSettings(settings) {
  return request("PUT", "/api/settings", settings);
}

export function putSecret(apiKey) {
  return request("POST", "/api/settings/secret", { api_key: apiKey });
}

export function llmCheck() {
  return request("POST", "/api/llm/check", {});
}

export function models() {
  return request("GET", "/api/models");
}

export function downloadModel(kind) {
  return request("POST", "/api/models/download", { kind });
}

export function dialogFiles() {
  return request("POST", "/api/dialog/files", {});
}

export function dialogFolder() {
  return request("POST", "/api/dialog/folder", {});
}

export function dialogDirectory() {
  return request("POST", "/api/dialog/directory", {});
}

export function dialogLog() {
  return request("POST", "/api/dialog/log", {});
}

export function dialogReveal(body) {
  return request("POST", "/api/dialog/reveal", body || {});
}

export function dropPaths(paths) {
  return request("POST", "/api/drop", { paths });
}

export function getPage(id) {
  return request("GET", `/api/pages/${encodeURIComponent(id)}`);
}

export function putDocument(id, baseVersion, document) {
  return request("PUT", `/api/pages/${encodeURIComponent(id)}/document`, {
    base_version: baseVersion,
    document,
  });
}

export function resetPage(id) {
  return request("POST", `/api/pages/${encodeURIComponent(id)}/reset`, {});
}

export function pageAction(id, action, regionId) {
  return request("POST", `/api/pages/${encodeURIComponent(id)}/action`, {
    action,
    region_id: regionId,
  });
}

export function translate(scope, pageId, extra) {
  const body = { scope };
  if (scope === "page") body.page_id = pageId;
  if (extra && extra.skip_ready) body.skip_ready = true;
  return request("POST", "/api/jobs/translate", body);
}

export function cancelJobs() {
  return request("POST", "/api/jobs/cancel", {});
}

export function exportPages(body) {
  return request("POST", "/api/jobs/export", body);
}

export function removePages(pageIds) {
  return request("POST", "/api/project/remove-pages", { page_ids: pageIds });
}

export function openRecent(id) {
  return request("POST", "/api/project/open-recent", { id });
}

export function jobs() {
  return request("GET", "/api/jobs");
}

export function pauseJobs() {
  return request("POST", "/api/jobs/pause", {});
}

export function resumeJobs() {
  return request("POST", "/api/jobs/resume", {});
}

export function retryErrors() {
  return request("POST", "/api/jobs/retry-errors", {});
}

export function importSources(body) {
  return request("POST", "/api/import", body || {});
}

export function pickFolder() {
  return request("POST", "/api/dialog/folder", { pick: true });
}

export function fontList() {
  return request("GET", "/api/fonts");
}

export function projectStyles() {
  return request("GET", "/api/project/styles");
}

export function putProjectStyles(styles) {
  return request("PUT", "/api/project/styles", { styles });
}

export function glossary() {
  return request("GET", "/api/project/glossary");
}

export function putGlossary(rows) {
  return request("PUT", "/api/project/glossary", { glossary: rows });
}

export function remoteStatus() {
  return request("GET", "/api/remote/status");
}

export function remotePair() {
  return request("POST", "/api/remote/pair-code", {});
}

export function remoteRevoke(id) {
  return request("POST", "/api/remote/revoke", { id });
}

export function sfxRestyle(pageId, regionId) {
  return request(
    "POST",
    `/api/pages/${encodeURIComponent(pageId)}/regions/${encodeURIComponent(regionId)}/sfx-style`,
    {},
  );
}

export async function previewRegion(pageId, regionId) {
  let response;
  try {
    response = await fetch(`/api/pages/${encodeURIComponent(pageId)}/preview-region`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "image/png" },
      body: JSON.stringify({ region_id: regionId }),
    });
  } catch (error) {
    throw new ApiError("Нет связи с программой", 0, null);
  }
  if (!response.ok) {
    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = null;
      }
    }
    const message = (data && (data.error || data.message)) || "Не удалось обновить предпросмотр";
    throw new ApiError(String(message), response.status, data);
  }
  const blob = await response.blob();
  return {
    url: URL.createObjectURL(blob),
    x: Number(response.headers.get("X-Offset-X")) || 0,
    y: Number(response.headers.get("X-Offset-Y")) || 0,
    width: 0,
    height: 0,
  };
}

export function imageUrl(pageId, kind, version) {
  const value = version == null ? "" : String(version);
  return `/api/pages/${encodeURIComponent(pageId)}/image/${encodeURIComponent(kind)}?v=${encodeURIComponent(value)}`;
}

const EVENT_NAMES = [
  "job.started",
  "job.progress",
  "page.updated",
  "job.finished",
  "job.failed",
  "job.cancelled",
  "llm.status",
  "worker.failed",
  "worker.restarting",
  "model.progress",
];

export function connectEvents(onEvent) {
  let source = null;
  let timer = 0;
  let delay = 1000;
  let stopped = false;

  function listen(name) {
    source.addEventListener(name, (event) => {
      deliver(name, event.data);
    });
  }

  function deliver(fallbackType, raw) {
    let data = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch (error) {
        data = {};
      }
    }
    let type = fallbackType;
    let payload = data;
    if (data && typeof data === "object" && typeof data.type === "string" && data.payload && typeof data.payload === "object") {
      type = data.type;
      payload = data.payload;
    }
    onEvent(type, payload || {});
  }

  function open() {
    if (stopped) return;
    source = new EventSource("/api/events");
    source.onopen = () => {
      delay = 1000;
    };
    source.onmessage = (event) => {
      deliver(event.type || "message", event.data);
    };
    EVENT_NAMES.forEach(listen);
    source.onerror = () => {
      if (stopped) return;
      source.close();
      window.clearTimeout(timer);
      timer = window.setTimeout(open, delay);
      delay = Math.min(delay * 2, 8000);
    };
  }

  open();
  return () => {
    stopped = true;
    window.clearTimeout(timer);
    if (source) source.close();
  };
}
