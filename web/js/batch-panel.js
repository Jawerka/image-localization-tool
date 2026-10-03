/* Панель пакетного прогона. Вид берётся из данных, не из адреса страницы. */

const SETTLED = new Set(["done", "edited", "offline", "error"]);
const ETA_DONE = new Set(["done", "edited", "offline"]);

const FILTERS = [
  { key: "error", icon: "error", label: "Ошибки" },
  { key: "fit", icon: "warning", label: "Не влезло" },
  { key: "offline", icon: "warning", label: "Без LLM" },
  { key: "edit", icon: "info", label: "Есть правки" },
];

/* Переключатели фильтра живут между вызовами render. Несколько включённых — ИЛИ. */
const filters = {
  error: false,
  fit: false,
  offline: false,
  edit: false,
};

const wired = new WeakSet();
const session = new WeakMap();

const ACTIONS = new Set(["pause", "resume", "retryErrors", "importFolder", "openGlossary"]);

/**
 * Рисует одну секцию прогона в host.
 * Повторный вызов заменяет innerHTML; слушатели вешаются один раз.
 * Возвращает краткую сводку прочитанных полей и нарисованных кнопок.
 */
export function render(root, state, actions) {
  const safeState = state && typeof state === "object" ? state : {};
  const safeActions = actions && typeof actions === "object" ? actions : {};
  const pages = pageList(safeState);
  const batch = batchOf(safeState);
  const kind = viewKind(pages, batch);
  const dataState = kind === "finished" || kind === "idle" ? "ready" : kind;
  const heading = headingText(kind, batch);
  const percent = kind === "empty" ? 0 : progressPercent(pages, batch);
  const eta = etaText(kind, pages, batch);
  const buttons = actionButtons(kind, pages, batch);
  const html = sectionHtml({
    dataState,
    kind,
    batch,
    heading,
    percent,
    eta,
    pages,
    state: safeState,
    buttons,
  });
  if (root && typeof root.addEventListener === "function") {
    session.set(root, { state: safeState, actions: safeActions });
    wire(root);
    root.innerHTML = html;
  }
  const labels = buttons.labels.length ? buttons.labels.join(", ") : "нет";
  return `Поля: pages[].id/name/chapter/status/progress/stage/overflow/thumb, activePageId, batch.status/startedAt/done/error/currentId. data-state=${dataState}. Кнопки: ${labels}.`;
}

function wire(root) {
  if (wired.has(root)) return;
  wired.add(root);
  root.addEventListener("click", onClick);
  root.addEventListener("keydown", onKey);
}

function onClick(event) {
  const root = event.currentTarget;
  const current = session.get(root);
  if (!current || !event.target || typeof event.target.closest !== "function") return;
  const filter = event.target.closest("[data-filter]");
  if (filter && root.contains(filter)) {
    const key = filter.getAttribute("data-filter");
    if (key && Object.prototype.hasOwnProperty.call(filters, key)) {
      filters[key] = !filters[key];
      render(root, current.state, current.actions);
      const again = typeof root.querySelector === "function"
        ? root.querySelector(`[data-filter="${key}"]`)
        : null;
      if (again && typeof again.focus === "function") again.focus();
    }
    return;
  }
  const button = event.target.closest("[data-action]");
  if (button && root.contains(button)) {
    const name = button.getAttribute("data-action");
    if (name === "focusPage") {
      const id = errorPageId(pageList(current.state), batchOf(current.state));
      if (id != null) callAction(current.actions, "focusPage", id);
      return;
    }
    if (ACTIONS.has(name)) callAction(current.actions, name);
    return;
  }
  const row = rowFromEvent(event, root);
  if (row) focusRow(row, current);
}

function onKey(event) {
  if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const root = event.currentTarget;
  const current = session.get(root);
  if (!current) return;
  const row = rowFromEvent(event, root);
  if (!row) return;
  event.preventDefault();
  focusRow(row, current);
}

function rowFromEvent(event, root) {
  if (!event.target || typeof event.target.closest !== "function") return null;
  if (event.target.closest("button, a, input, select, textarea")) return null;
  const row = event.target.closest("[data-page-index]");
  if (!row || !root.contains(row)) return null;
  return row;
}

function focusRow(row, current) {
  const index = Number(row.getAttribute("data-page-index"));
  if (!Number.isInteger(index)) return;
  const page = pageList(current.state)[index];
  if (!page || page.id == null || page.id === "") return;
  callAction(current.actions, "focusPage", page.id);
}

function callAction(actions, name, ...args) {
  if (!actions || typeof actions[name] !== "function") return;
  actions[name](...args);
}

function pageList(state) {
  if (!state || !Array.isArray(state.pages)) return [];
  return state.pages;
}

function batchOf(state) {
  if (!state || !state.batch || typeof state.batch !== "object") return {};
  return state.batch;
}

function batchStatus(batch) {
  if (!batch || typeof batch.status !== "string" || !batch.status) return "idle";
  return batch.status;
}

function hasBatchError(batch) {
  const value = batch && batch.error;
  if (typeof value === "string") return value.trim().length > 0;
  return Boolean(value);
}

/* Пусто важнее прогона. Пауза с текстом ошибки — это ошибка, без текста — пауза. */
function viewKind(pages, batch) {
  if (!pages.length) return "empty";
  const status = batchStatus(batch);
  const failed = hasBatchError(batch);
  if (status === "running" || (status === "paused" && !failed)) return "loading";
  if (status === "error" || (status === "paused" && failed)) return "error";
  if (status === "finished") return "finished";
  return "idle";
}

function headingText(kind, batch) {
  if (kind === "empty") return "В проекте нет страниц";
  if (kind === "loading") {
    return batchStatus(batch) === "paused" ? "Прогон на паузе" : "Идёт пакетный прогон";
  }
  if (kind === "error") return "Ошибка на странице";
  if (kind === "finished") return "Прогон завершён";
  return "Страницы проекта";
}

function progressPercent(pages, batch) {
  const total = pages.length;
  if (!total) return 0;
  let settled = 0;
  pages.forEach((page) => {
    if (page && SETTLED.has(page.status)) settled += 1;
  });
  let percent = Math.round((100 * settled) / total);
  if (batchStatus(batch) === "running" && typeof batch.done === "number" && Number.isFinite(batch.done)) {
    const fromBatch = Math.round((100 * batch.done) / total);
    if (fromBatch > percent) percent = fromBatch;
  }
  return clampPercent(percent);
}

function clampPercent(value) {
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return 0;
  return Math.min(100, Math.max(0, number));
}

/* Для времени Number(batch.done), если оно конечно; иначе done|edited|offline. Ошибки сюда не входят. */
function etaDoneCount(batch, pages) {
  const raw = Number(batch && batch.done);
  if (Number.isFinite(raw)) return raw;
  let count = 0;
  pages.forEach((page) => {
    if (page && ETA_DONE.has(page.status)) count += 1;
  });
  return count;
}

function etaText(kind, pages, batch) {
  if (kind === "empty") return "Откройте папку главы. Продолжить нечего.";
  if (kind === "error" || batchStatus(batch) === "paused") return "пауза";
  if (kind === "finished") return "готово";
  if (batchStatus(batch) === "running") {
    const done = etaDoneCount(batch, pages);
    if (!(done > 0) || !Number.isFinite(batch.startedAt)) return "считаем время";
    const elapsed = Date.now() - batch.startedAt;
    const etaMs = (elapsed / done) * (pages.length - done);
    if (!Number.isFinite(etaMs)) return "считаем время";
    if (etaMs < 60000) {
      const seconds = Math.max(0, Math.round(etaMs / 1000));
      return `осталось около ${seconds} с`;
    }
    const minutes = Math.max(1, Math.round(etaMs / 60000));
    return `осталось около ${minutes} мин`;
  }
  return "прогон не запущен";
}

function counts(pages) {
  const tally = { done: 0, queue: 0, error: 0, fit: 0, offline: 0, edit: 0 };
  pages.forEach((page) => {
    if (!page || typeof page !== "object") return;
    if (page.status === "done") tally.done += 1;
    if (page.status === "queued" || page.status === "running") tally.queue += 1;
    if (page.status === "error") tally.error += 1;
    if (page.overflow) tally.fit += 1;
    if (page.status === "offline") tally.offline += 1;
    if (page.status === "edited") tally.edit += 1;
  });
  return tally;
}

function pageMatches(page) {
  const active = FILTERS.filter((item) => filters[item.key]);
  if (!active.length) return true;
  if (!page || typeof page !== "object") return false;
  return active.some((item) => {
    if (item.key === "error") return page.status === "error";
    if (item.key === "fit") return Boolean(page.overflow);
    if (item.key === "offline") return page.status === "offline";
    if (item.key === "edit") return page.status === "edited";
    return false;
  });
}

function chapterKey(page) {
  if (!page || typeof page.chapter !== "string") return "";
  if (!page.chapter.trim()) return "";
  return page.chapter;
}

function statusView(page) {
  const status = page && typeof page.status === "string" ? page.status : "idle";
  if (status === "queued") {
    return { cls: "page__status--queue", icon: "chevron", extra: "icon--right", text: "в очереди" };
  }
  if (status === "running") {
    const progress = clampPercent(page.progress);
    const stage = typeof page.stage === "string" && page.stage.trim() ? page.stage : "";
    const text = stage ? `идёт ${progress} % · ${stage}` : `идёт ${progress} %`;
    return { cls: "page__status--run", icon: "play", extra: "", text };
  }
  if (status === "done") return { cls: "page__status--done", icon: "check", extra: "", text: "готово" };
  if (status === "edited") return { cls: "page__status--edit", icon: "info", extra: "", text: "есть правки" };
  if (status === "offline") return { cls: "page__status--offline", icon: "warning", extra: "", text: "без LLM" };
  if (status === "error") return { cls: "page__status--error", icon: "error", extra: "", text: "ошибка" };
  return { cls: "page__status--idle", icon: "file", extra: "", text: "не начата" };
}

function errorPageId(pages, batch) {
  const found = pages.find((page) => page && page.status === "error" && page.id != null && page.id !== "");
  if (found) return found.id;
  if (batch.currentId != null && batch.currentId !== "") return batch.currentId;
  return null;
}

function sameId(a, b) {
  if (a == null || b == null || a === "" || b === "") return false;
  return String(a) === String(b);
}

function isCurrent(page, state, batch) {
  if (!page || page.id == null) return false;
  if (sameId(page.id, state.activePageId)) return true;
  return batchStatus(batch) === "running" && sameId(page.id, batch.currentId);
}

function sectionHtml(model) {
  const busy = model.kind === "loading" && batchStatus(model.batch) === "running" ? ` aria-busy="true"` : "";
  const banner = model.kind === "error" ? bannerHtml(model.batch) : "";
  const filtersBlock = model.kind === "empty" ? "" : filtersHtml();
  const hint = model.kind === "empty"
    ? ""
    : `<p id="run-next" class="field-hint"><kbd class="kbd">N</kbd> — следующая проблемная страница</p>`;
  const chapters = model.kind === "empty" ? "" : chaptersHtml(model.pages, model.state, model.batch);
  return `<section class="run-state" data-state="${model.dataState}"${busy}>
    <div class="run-scroll">
      <h2>${esc(model.heading)}</h2>
      ${banner}
      <div class="run-top">
        ${progressHtml(model.percent, model.eta)}
        ${countsHtml(counts(model.pages))}
        ${filtersBlock}
        ${model.buttons.html}
        ${hint}
      </div>
      ${chapters}
    </div>
  </section>`;
}

function progressHtml(percent, eta) {
  return `<div class="run-progress">
      <div class="run-progress__row">
        <span id="run-prog-label">Общий прогресс</span>
        <span class="run-percent">${percent} %</span>
      </div>
      <progress id="run-prog" max="100" value="${percent}" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100" aria-labelledby="run-prog-label" aria-describedby="run-eta">${percent} %</progress>
      <p id="run-eta" class="run-eta">${esc(eta)}</p>
    </div>`;
}

function countsHtml(tally) {
  return `<ul class="run-counts" aria-label="Счётчики по статусу">
      <li class="page__status page__status--done">${icon("check")} готово <span class="run-num">${tally.done}</span></li>
      <li class="page__status page__status--queue">${icon("chevron", "icon--right")} в очереди <span class="run-num">${tally.queue}</span></li>
      <li class="page__status page__status--error">${icon("error")} ошибка <span class="run-num">${tally.error}</span></li>
      <li class="page__status page__status--fit">${icon("warning")} не влезло <span class="run-num">${tally.fit}</span></li>
      <li class="page__status page__status--offline">${icon("warning")} без LLM <span class="run-num">${tally.offline}</span></li>
      <li class="page__status page__status--edit">${icon("info")} есть правки <span class="run-num">${tally.edit}</span></li>
    </ul>`;
}

function filtersHtml() {
  const buttons = FILTERS.map((item) => {
    const pressed = filters[item.key] ? "true" : "false";
    return `<button type="button" class="btn btn-ghost" data-filter="${item.key}" aria-pressed="${pressed}">${icon(item.icon)} ${item.label}</button>`;
  }).join("");
  return `<div class="run-filters" role="group" aria-label="Фильтр страниц">${buttons}</div>`;
}

function actionButtons(kind, pages, batch) {
  const items = [];
  const add = (action, variant, iconName, label, describedBy) => {
    const described = describedBy ? ` aria-describedby="${describedBy}"` : "";
    items.push({
      label,
      html: `<button type="button" class="btn ${variant}" data-action="${action}"${described}>${icon(iconName)} ${label}</button>`,
    });
  };
  if (kind === "empty") {
    add("importFolder", "btn-primary", "folder", "Открыть папку…", "run-eta");
  } else if (kind === "loading") {
    if (batchStatus(batch) === "paused") add("resume", "btn-primary", "play", "Продолжить", "run-eta");
    else add("pause", "btn-accent", "stop", "Пауза", "run-eta");
  } else if (kind === "error") {
    add("resume", "btn-primary", "play", "Продолжить", "run-banner");
    add("retryErrors", "btn-accent", "error", "Повторить ошибки", "run-banner");
    add("focusPage", "btn-accent", "file", "Открыть страницу", "run-banner");
  } else if (kind === "finished") {
    add("resume", "btn-primary", "play", "Продолжить", "run-eta");
    add("openGlossary", "btn-accent", "file", "Глоссарий");
    if (pages.some((page) => page && page.status === "error")) {
      add("retryErrors", "btn-accent", "error", "Повторить ошибки");
    }
  } else {
    add("importFolder", "btn-primary", "folder", "Открыть папку…");
    add("openGlossary", "btn-accent", "file", "Глоссарий");
  }
  return {
    html: `<div class="run-actions">${items.map((item) => item.html).join("")}</div>`,
    labels: items.map((item) => item.label),
  };
}

function bannerHtml(batch) {
  const text = typeof batch.error === "string" && batch.error.trim()
    ? batch.error
    : "Прогон остановлен из-за ошибки.";
  return `<div class="banner banner--error" id="run-banner" role="alert">${icon("error", "banner__icon")}<p class="banner__text">${esc(text)}</p></div>`;
}

function chaptersHtml(pages, state, batch) {
  const showHeadings = pages.some((page) => chapterKey(page));
  const groups = [];
  const byKey = new Map();
  pages.forEach((page, index) => {
    if (!pageMatches(page)) return;
    const key = showHeadings ? chapterKey(page) : "";
    let group = byKey.get(key);
    if (!group) {
      group = { title: showHeadings ? (key || "Без главы") : "", items: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.items.push({ page, index });
  });
  const blocks = groups.map((group, groupIndex) => {
    const items = group.items.map(({ page, index }) => pageRowHtml(page, index, state, batch)).join("");
    const list = `<ul class="chapter__list">${items}</ul>`;
    if (!showHeadings) return list;
    const id = `run-chapter-${groupIndex}`;
    return `<section class="chapter" aria-labelledby="${id}"><h3 id="${id}">${esc(group.title)}</h3>${list}</section>`;
  }).join("");
  return `<div class="run-chapters" aria-describedby="run-next">${blocks}</div>`;
}

function pageRowHtml(page, index, state, batch) {
  const view = statusView(page || {});
  const current = isCurrent(page, state, batch) ? " is-current" : "";
  const busy = batchStatus(batch) === "running" && page && page.status === "running" ? ` aria-busy="true"` : "";
  const idAttr = page && page.id != null && page.id !== "" ? ` data-page-id="${esc(page.id)}"` : "";
  const name = page && page.name != null ? page.name : "";
  const num = String(index + 1).padStart(2, "0");
  return `<li class="page${current}" data-page-index="${index}"${idAttr} tabindex="0"${busy}>${thumbHtml(page)}<span class="page__body"><span class="page__title"><span class="page__num">${num}</span> <span class="page__name">${esc(name)}</span></span><span class="page__status ${view.cls}">${icon(view.icon, view.extra)} <span>${esc(view.text)}</span></span></span></li>`;
}

function thumbHtml(page) {
  const thumb = page && typeof page.thumb === "string" ? page.thumb : "";
  if (!thumb.trim()) return `<span class="page__thumb" aria-hidden="true"></span>`;
  return `<img class="page__thumb" src="${esc(thumb)}" alt="">`;
}

function icon(name, extra) {
  const cls = extra ? `icon ${extra}` : "icon";
  return `<svg class="${cls}" aria-hidden="true"><use href="icons/icons.svg#${name}"></use></svg>`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}
