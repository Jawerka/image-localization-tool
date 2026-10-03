/* Список страниц: выбор, итог, контекстное меню. */

import { imageUrl } from "./api.js";
import { getState, moveFocus, readyCount, selectPages, setAnchor, statusText, subscribe } from "./state.js";

const ICONS = {
  idle: ["file", "page__status--idle", ""],
  queued: ["chevron", "page__status--queue", "icon--right"],
  running: ["play", "page__status--run", ""],
  done: ["check", "page__status--done", ""],
  edited: ["brush", "page__status--edit", ""],
  offline: ["warning", "page__status--offline", ""],
  error: ["error", "page__status--error", ""],
};

let list;
let sum;
let menu;
let menuTitle;
let contextId = "";
let focusFromKeys = false;
let onCommand = () => {};

function icon(id, extra) {
  const cls = extra ? `icon ${extra}` : "icon";
  return `<svg class="${cls}" aria-hidden="true"><use href="icons/icons.svg#${id}"></use></svg>`;
}

export function init(command) {
  onCommand = command;
  list = document.querySelector("[data-role='page-list']");
  sum = document.querySelector(".pages__sum span");
  menu = document.querySelector("[data-role='context-menu']");
  menuTitle = document.querySelector("[data-role='context-title']");
  list.addEventListener("click", onClick);
  list.addEventListener("keydown", onListKey);
  list.addEventListener("contextmenu", onContext);
  menu.addEventListener("click", onMenuClick);
  menu.addEventListener("keydown", onMenuKey);
  document.addEventListener("pointerdown", (event) => {
    if (!menu.hidden && !menu.contains(event.target)) closeMenu();
  });
  window.addEventListener("resize", closeMenu);
  list.addEventListener("scroll", closeMenu);
  subscribe(render);
  render(getState());
}

export function menuOpen() {
  return menu && !menu.hidden;
}

export function closeMenu() {
  if (!menu || menu.hidden) return false;
  menu.hidden = true;
  const current = list.querySelector("[tabindex='0']");
  current?.focus();
  return true;
}

function render(current) {
  const pages = current.pages;
  if (!pages.length) {
    list.innerHTML = '<p class="pages__empty">Нет страниц</p>';
    list.tabIndex = 0;
  } else {
    list.tabIndex = -1;
    const focusId = current.focusPageId || current.activePageId;
    const grouped = pages.some((page) => page.chapter);
    let lastChapter = null;
    list.innerHTML = pages.map((page, index) => {
      let heading = "";
      if (grouped && page.chapter !== lastChapter) {
        lastChapter = page.chapter;
        const title = page.chapter || "Без главы";
        heading = `<div class="pages__chapter" role="presentation">${escapeText(title)}</div>`;
      }
      return heading + optionHtml(page, index, current, focusId);
    }).join("");
  }
  if (sum) sum.textContent = `${readyCount(pages)} из ${pages.length} готово`;
  if (focusFromKeys) {
    const node = list.querySelector("[tabindex='0']");
    node?.focus();
    focusFromKeys = false;
  }
}

function optionHtml(page, index, current, focusId) {
  const status = page.status || "idle";
  const meta = ICONS[status] || ICONS.idle;
  const selected = current.selectedPageIds.includes(page.id);
  const tab = page.id === focusId ? 0 : -1;
  const num = String(index + 1).padStart(2, "0");
  const label = statusText(page);
  const busy = status === "running" ? ' aria-busy="true"' : "";
  return `<div class="page" role="option" data-page-id="${escapeAttr(page.id)}" aria-selected="${selected ? "true" : "false"}" tabindex="${tab}"${busy}>
    <img class="page__thumb" src="${imageUrl(page.id, "thumb", page.version)}" alt="">
    <span class="page__body">
      <span class="page__title"><span class="page__num">${num}</span> <span class="page__name">${escapeText(page.name)}</span></span>
      <span class="page__status ${meta[1]}">${icon(meta[0], meta[2])} <span>${escapeText(label)}</span></span>
    </span>
  </div>`;
}

function onClick(event) {
  const option = event.target.closest("[data-page-id]");
  if (!option) return;
  choose(option.dataset.pageId, event, false);
}

function onListKey(event) {
  const pages = getState().pages;
  if (!pages.length) return;
  const key = event.key;
  if (key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End") {
    event.preventDefault();
    move(key, event);
    return;
  }
  if (key === " " || key === "Spacebar") {
    event.preventDefault();
    const id = getState().focusPageId;
    if (id) choose(id, event, true);
    return;
  }
  if (key === "ContextMenu" || (key === "F10" && event.shiftKey)) {
    event.preventDefault();
    const id = getState().focusPageId || getState().activePageId;
    const node = list.querySelector(`[data-page-id="${cssEscape(id)}"]`);
    if (!node) return;
    const rect = node.getBoundingClientRect();
    openMenu(id, rect.left + 8, rect.bottom);
  }
}

function move(key, event) {
  const current = getState();
  const pages = current.pages;
  const focus = current.focusPageId || current.activePageId || pages[0].id;
  let index = pages.findIndex((page) => page.id === focus);
  if (index < 0) index = 0;
  if (key === "Home") index = 0;
  else if (key === "End") index = pages.length - 1;
  else if (key === "ArrowDown") index = Math.min(pages.length - 1, index + 1);
  else index = Math.max(0, index - 1);
  const id = pages[index].id;
  focusFromKeys = true;
  if (event.ctrlKey) {
    moveFocus(id);
    return;
  }
  if (event.shiftKey) {
    const anchor = current.anchorPageId || focus;
    const start = pages.findIndex((page) => page.id === anchor);
    const from = Math.min(start < 0 ? index : start, index);
    const to = Math.max(start < 0 ? index : start, index);
    selectPages(pages.slice(from, to + 1).map((page) => page.id), id, id);
    return;
  }
  setAnchor(id);
  selectPages([id], id, id);
}

function choose(id, event, fromKeyboard) {
  const current = getState();
  const ids = current.pages.map((page) => page.id);
  focusFromKeys = fromKeyboard;
  if (event.shiftKey && current.anchorPageId) {
    const start = ids.indexOf(current.anchorPageId);
    const end = ids.indexOf(id);
    const from = Math.min(start < 0 ? end : start, end);
    const to = Math.max(start < 0 ? end : start, end);
    selectPages(ids.slice(Math.max(0, from), to + 1), id, id);
    return;
  }
  if (event.ctrlKey || event.metaKey) {
    const selected = new Set(current.selectedPageIds);
    if (selected.has(id) && selected.size > 1) selected.delete(id);
    else selected.add(id);
    const next = ids.filter((item) => selected.has(item));
    const active = next.includes(id) ? id : next[0];
    setAnchor(id);
    selectPages(next, active, id);
    return;
  }
  setAnchor(id);
  selectPages([id], id, id);
}

function onContext(event) {
  const option = event.target.closest("[data-page-id]");
  if (!option) return;
  event.preventDefault();
  const id = option.dataset.pageId;
  const current = getState();
  if (!current.selectedPageIds.includes(id)) {
    setAnchor(id);
    selectPages([id], id, id);
  } else {
    moveFocus(id);
  }
  openMenu(id, event.clientX, event.clientY);
}

function openMenu(pageId, x, y) {
  contextId = pageId;
  const page = getState().pages.find((item) => item.id === pageId);
  const count = getState().selectedPageIds.includes(pageId) ? getState().selectedPageIds.length : 1;
  const title = count > 1 ? `Выбрано ${count}` : (page ? page.name : "");
  menuTitle.textContent = title;
  menu.setAttribute("aria-label", title || "Страница");
  menu.hidden = false;
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
  const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.querySelector("[role='menuitem']")?.focus();
}

function onMenuClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const ids = targetIds();
  closeMenu();
  onCommand(action, ids, contextId);
}

function onMenuKey(event) {
  const items = [...menu.querySelectorAll("[role='menuitem']")];
  const index = items.indexOf(document.activeElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const next = event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
    items[next]?.focus();
  }
  if (event.key === "Home") {
    event.preventDefault();
    items[0]?.focus();
  }
  if (event.key === "End") {
    event.preventDefault();
    items[items.length - 1]?.focus();
  }
}

function targetIds() {
  const current = getState();
  if (current.selectedPageIds.includes(contextId)) return current.selectedPageIds.slice();
  return [contextId];
}

function escapeText(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function escapeAttr(value) {
  return escapeText(value);
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(String(value));
  return String(value).replace(/"/g, '\\"');
}
