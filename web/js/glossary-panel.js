/* Панель глоссария серии внутри диалога: одна таблица, четыре состояния. */

const INTRO = "Записи действуют на всю серию, род нужен для русского согласования.";

const COPY = {
  loading: {
    title: "Читаем глоссарий",
    hint: "Читаем файл глоссария серии.",
  },
  error: {
    title: "Не удалось сохранить",
    hint: "Строки на экране не записаны в файл.",
  },
  empty: {
    title: "В глоссарии пока нет записей",
    hint: "Сохранять пока нечего.",
  },
  ready: {
    title: "Глоссарий серии",
    hint: "Сохранение запишет эти строки в файл глоссария серии.",
  },
};

const FIELDS = ["source", "target", "gender", "note"];
const FIELD_SET = new Set(FIELDS);

/* Ставится только кнопкой «Добавить строку», чтобы чужой render не крал фокус. */
let focusNewSource = false;

let idSeq = 0;
const bags = new WeakMap();

/**
 * Нарисовать глоссарий в root.
 * rows === null — чтение файла; массив — строки на экране.
 * actions.onChange(nextRows) после добавления, удаления и правки поля.
 */
export function render(root, rows, actions) {
  if (!root || root.nodeType !== 1) return;
  const bag = ensureBag(root);
  const opts = actions && typeof actions === "object" ? actions : {};
  bag.actions = opts;
  const mode = resolveMode(rows, opts);
  bag.mode = mode;
  const shown = viewRows(bag, rows);
  bag.rows = shown;
  const err = errorText(opts);
  const kind = saveKind(opts);
  const sig = `${mode}|${shown.length}|${kind}`;
  wire(root);

  const sameShape = bag.sig === sig && root.querySelector("form.glossary-state");
  if (sameShape) {
    syncFields(root, shown);
    const bannerText = root.querySelector(".banner__text");
    if (bannerText && err && bannerText.textContent !== err) bannerText.textContent = err;
    if (focusNewSource) settleFocus(root, mode, null);
    return;
  }

  const saved = captureFocus(root);
  const ids = ensureIds(root);
  root.innerHTML = buildPanel(mode, shown, err, kind, ids);
  bag.sig = sig;
  settleFocus(root, mode, saved);
}

function ensureBag(root) {
  let bag = bags.get(root);
  if (!bag) {
    bag = {
      actions: {},
      rows: [],
      mode: "loading",
      cached: null,
      sig: "",
    };
    bags.set(root, bag);
  }
  return bag;
}

function wire(root) {
  if (root.dataset.wired) return;
  root.dataset.wired = "1";
  root.addEventListener("input", onField);
  root.addEventListener("change", onField);
  root.addEventListener("click", onClick);
  root.addEventListener("submit", (event) => event.preventDefault());
}

function onField(event) {
  const root = event.currentTarget;
  const bag = bags.get(root);
  const el = event.target instanceof Element ? event.target : null;
  if (!bag || !el || bag.mode === "loading") return;
  const field = el.dataset.field;
  if (!FIELD_SET.has(field)) return;
  if (el.disabled) return;
  const index = Number(el.dataset.index);
  if (!Number.isInteger(index) || index < 0 || index >= bag.rows.length) return;
  const value = field === "gender" ? normalizeGender(el.value) : el.value;
  if (bag.rows[index][field] === value) return;
  const next = snapshot(bag.rows);
  next[index] = { ...next[index], [field]: value };
  bag.rows = snapshot(next);
  bag.cached = snapshot(next);
  if (field === "source") {
    const tr = el.closest("tr");
    if (tr) paintRowLabels(tr, value);
  }
  emit(bag, next);
}

function onClick(event) {
  const root = event.currentTarget;
  const bag = bags.get(root);
  const origin = event.target instanceof Element ? event.target : event.target?.parentElement;
  const button = origin?.closest?.("[data-action]");
  if (!bag || !button || !root.contains(button)) return;
  if (button.disabled || bag.mode === "loading") return;
  const action = button.dataset.action;
  if (action === "add") {
    const next = snapshot(bag.rows);
    next.push({ source: "", target: "", gender: "", note: "" });
    bag.rows = snapshot(next);
    bag.cached = snapshot(next);
    focusNewSource = true;
    emit(bag, next);
    return;
  }
  if (action === "delete") {
    const index = Number(button.dataset.index);
    if (!Number.isInteger(index) || index < 0 || index >= bag.rows.length) return;
    const next = snapshot(bag.rows);
    next.splice(index, 1);
    bag.rows = snapshot(next);
    bag.cached = snapshot(next);
    emit(bag, next);
    return;
  }
  if (action === "save") {
    const opts = bag.actions;
    if (errorText(opts) && typeof opts.onRetry === "function") {
      opts.onRetry();
      return;
    }
    if (typeof opts.onSave === "function") opts.onSave();
  }
}

function emit(bag, rows) {
  const next = snapshot(rows);
  const fn = bag.actions.onChange;
  if (typeof fn === "function") fn(next);
}

function resolveMode(rows, actions) {
  if (rows == null) return "loading";
  if (!Array.isArray(rows)) return "empty";
  if (errorText(actions)) return "error";
  if (rows.length === 0) return "empty";
  return "ready";
}

function errorText(actions) {
  if (!actions || typeof actions.error !== "string" || actions.error === "") return "";
  return actions.error;
}

function saveKind(actions) {
  if (errorText(actions) && typeof actions.onRetry === "function") return "retry";
  if (typeof actions.onSave === "function") return "save";
  return "none";
}

/* null оставляет прошлые строки этого root; без кэша тело таблицы пустое. */
function viewRows(bag, rows) {
  if (rows == null) return bag.cached ? snapshot(bag.cached) : [];
  const list = Array.isArray(rows) ? rows : [];
  const next = list.map((item) => normalizeRow(item));
  bag.cached = snapshot(next);
  return snapshot(next);
}

function buildPanel(mode, rows, err, kind, ids) {
  const busy = mode === "loading" ? " aria-busy=\"true\"" : "";
  return `<section data-state="${mode}"${busy}>
<form class="glossary-state"${busy}>
<div class="glossary-scroll">
${scrollHtml(mode, rows, err, ids)}
</div>
<footer class="settings__footer">
${addButtonHtml(mode)}
${saveButtonHtml(mode, kind, ids)}
</footer>
</form>
</section>`;
}

function scrollHtml(mode, rows, err, ids) {
  const copy = COPY[mode];
  const disabled = mode === "loading";
  const head = `<h2 id="${ids.title}">${copy.title}</h2><p class="settings__intro" id="${ids.intro}">${INTRO}</p>`;
  const hint = mode === "loading"
    ? `<p id="${ids.hint}" class="field-hint">${icon("info")}${copy.hint}</p>`
    : `<p id="${ids.hint}" class="field-hint">${copy.hint}</p>`;
  const banner = mode === "error"
    ? `<div class="banner banner--error" id="${ids.banner}" role="alert">${icon("error", "banner__icon")}<p class="banner__text">${escapeHtml(err)}</p></div>`
    : "";
  const table = `<table class="gloss" aria-labelledby="${ids.title}" aria-describedby="${ids.intro}">
<thead><tr>
<th scope="col">Оригинал</th>
<th scope="col">Перевод</th>
<th scope="col">Род</th>
<th scope="col">Заметка</th>
<th scope="col">Действие</th>
</tr></thead>
<tbody>${rows.map((row, index) => buildRow(row, index, ids, disabled)).join("")}</tbody>
</table>`;
  const rule = `<hr class="settings__rule">`;
  if (mode === "loading") return `${head}${hint}${rule}${table}`;
  if (mode === "error") return `${head}${banner}${hint}${rule}${table}`;
  return `${head}${rule}${table}${hint}`;
}

function buildRow(row, index, ids, disabled) {
  const dis = disabled ? " disabled" : "";
  const sourceId = ids.field("source", index);
  const targetId = ids.field("target", index);
  const genderId = ids.field("gender", index);
  const noteId = ids.field("note", index);
  const name = row.source ? row.source : "новая строка";
  const delName = row.source ? row.source : "строку";
  return `<tr>
<td>
<label class="sr-only" for="${sourceId}">${escapeHtml(`Оригинал, ${name}`)}</label>
<input id="${sourceId}" class="input" type="text" value="${escapeHtml(row.source)}" spellcheck="false" autocomplete="off" data-field="source" data-index="${index}"${dis}>
</td>
<td>
<label class="sr-only" for="${targetId}">${escapeHtml(`Перевод, ${name}`)}</label>
<input id="${targetId}" class="input" type="text" value="${escapeHtml(row.target)}" autocomplete="off" data-field="target" data-index="${index}"${dis}>
</td>
<td>
<label class="sr-only" for="${genderId}">${escapeHtml(`Род, ${name}`)}</label>
<select id="${genderId}" class="select" aria-describedby="${ids.intro}" data-field="gender" data-index="${index}"${dis}>
${genderOptions(row.gender)}
</select>
</td>
<td>
<label class="sr-only" for="${noteId}">${escapeHtml(`Заметка, ${name}`)}</label>
<input id="${noteId}" class="input" type="text" value="${escapeHtml(row.note)}" autocomplete="off" data-field="note" data-index="${index}"${dis}>
</td>
<td>
<button type="button" class="btn btn-ghost" data-action="delete" data-index="${index}" aria-label="${escapeHtml(`Удалить ${delName}`)}"${dis}>${icon("delete")}Удалить</button>
</td>
</tr>`;
}

function genderOptions(gender) {
  const items = [
    ["m", "мужской"],
    ["f", "женский"],
    ["n", "средний"],
    ["", "не указан"],
  ];
  return items.map(([value, label]) => {
    const selected = value === gender ? " selected" : "";
    return `<option value="${escapeHtml(value)}"${selected}>${label}</option>`;
  }).join("");
}

function addButtonHtml(mode) {
  const dis = mode === "loading" ? " disabled" : "";
  return `<button type="button" class="btn btn-accent" data-action="add"${dis}>${icon("add")}Добавить строку</button>`;
}

function saveButtonHtml(mode, kind, ids) {
  if (kind === "none") return "";
  const label = kind === "retry" ? "Повторить сохранение" : "Сохранить";
  const described = mode === "error" ? ids.banner : ids.hint;
  const dis = mode === "loading" ? " disabled" : "";
  return `<button type="button" class="btn btn-primary is-commit" data-action="save" aria-describedby="${described}"${dis}>${label}</button>`;
}

function icon(id, extra) {
  const cls = extra ? `icon ${extra}` : "icon";
  return `<svg class="${cls}" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

function ensureIds(root) {
  if (!root.dataset.glossId) {
    idSeq += 1;
    root.dataset.glossId = `gp${idSeq}`;
  }
  const base = root.dataset.glossId;
  return {
    title: `${base}-title`,
    intro: `${base}-intro`,
    hint: `${base}-hint`,
    banner: `${base}-banner`,
    field(kind, index) {
      return `${base}-${kind}-${index}`;
    },
  };
}

/* Повторный render с тем же числом строк не сбрасывает каретку. */
function syncFields(root, rows) {
  rows.forEach((row, index) => {
    FIELDS.forEach((field) => {
      const el = root.querySelector(`[data-field="${field}"][data-index="${index}"]`);
      if (!el || el.value === row[field]) return;
      const focused = document.activeElement === el;
      let start = null;
      let end = null;
      if (focused) {
        try {
          if (typeof el.selectionStart === "number") {
            start = el.selectionStart;
            end = el.selectionEnd;
          }
        } catch (err) {
          start = null;
        }
      }
      el.value = row[field];
      if (!focused) return;
      el.focus();
      if (typeof start !== "number" || typeof el.setSelectionRange !== "function") return;
      try {
        const max = el.value.length;
        const caretEnd = typeof end === "number" ? end : start;
        el.setSelectionRange(Math.min(start, max), Math.min(caretEnd, max));
      } catch (err) {
        /* У select нет каретки. */
      }
    });
    const source = root.querySelector(`[data-field="source"][data-index="${index}"]`);
    const tr = source?.closest("tr");
    if (tr) paintRowLabels(tr, row.source);
  });
}

function paintRowLabels(tr, source) {
  const name = source ? source : "новая строка";
  const delName = source ? source : "строку";
  const texts = {
    source: `Оригинал, ${name}`,
    target: `Перевод, ${name}`,
    gender: `Род, ${name}`,
    note: `Заметка, ${name}`,
  };
  tr.querySelectorAll("[data-field]").forEach((el) => {
    const label = el.id ? tr.querySelector(`label[for="${el.id}"]`) : null;
    if (label && texts[el.dataset.field]) label.textContent = texts[el.dataset.field];
  });
  const button = tr.querySelector("[data-action='delete']");
  if (button) button.setAttribute("aria-label", `Удалить ${delName}`);
}

function captureFocus(root) {
  const el = document.activeElement;
  if (!el || el === document.body || !root.contains(el)) return null;
  const field = el.dataset?.field;
  const index = el.dataset?.index;
  if (!FIELD_SET.has(field) || !/^\d+$/.test(String(index))) return null;
  const saved = { field, index: String(index) };
  try {
    if (typeof el.selectionStart === "number") {
      saved.start = el.selectionStart;
      saved.end = el.selectionEnd;
    }
  } catch (err) {
    /* Поле без каретки. */
  }
  return saved;
}

function restoreFocus(root, saved) {
  if (!saved || !FIELD_SET.has(saved.field) || !/^\d+$/.test(String(saved.index))) return;
  const el = root.querySelector(`[data-field="${saved.field}"][data-index="${saved.index}"]`);
  if (!el || el.disabled) return;
  el.focus();
  if (typeof saved.start !== "number" || typeof el.setSelectionRange !== "function") return;
  try {
    el.setSelectionRange(saved.start, typeof saved.end === "number" ? saved.end : saved.start);
  } catch (err) {
    /* Поле без каретки. */
  }
}

function settleFocus(root, mode, saved) {
  if (focusNewSource && mode !== "loading") {
    focusNewSource = false;
    const inputs = root.querySelectorAll("[data-field='source']");
    const el = inputs.length ? inputs[inputs.length - 1] : null;
    if (el && !el.disabled) {
      el.focus();
      return;
    }
  }
  restoreFocus(root, saved);
}

function normalizeRow(row) {
  const item = row && typeof row === "object" ? row : {};
  return {
    source: asText(item.source),
    target: asText(item.target),
    gender: normalizeGender(item.gender),
    note: asText(item.note),
  };
}

function normalizeGender(value) {
  if (typeof value !== "string") return "";
  const key = value.trim().toLowerCase();
  if (key === "m" || key === "male") return "m";
  if (key === "f" || key === "female") return "f";
  if (key === "n" || key === "neutral") return "n";
  return "";
}

function asText(value) {
  return typeof value === "string" ? value : "";
}

function snapshot(rows) {
  return rows.map((row) => ({
    source: row.source,
    target: row.target,
    gender: row.gender,
    note: row.note,
  }));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}
