/* Панели, поповеры дока — оболочка v2. */

export function initShellChrome() {
  const panels = [
    { cls: "is-pages-collapsed", id: "workspace-pages", name: "Список страниц" },
    { cls: "is-inspector-collapsed", id: "workspace-inspector", name: "Инспектор" },
  ];
  const shell = document.querySelector("[data-role='shell']");
  let small = false;

  function syncPanels() {
    for (const { cls, id, name } of panels) {
      const panel = document.getElementById(id);
      const expanded = !document.body.classList.contains(cls);
      const buttons = [...document.querySelectorAll(`[data-toggle-panel='${cls}']`)];
      if (!expanded && panel?.contains(document.activeElement)) {
        buttons.find((button) => button.querySelector("[data-panel-label]"))?.focus();
      }
      if (panel) {
        panel.inert = !expanded;
        panel.setAttribute("aria-hidden", String(!expanded));
      }
      for (const button of buttons) {
        button.setAttribute("aria-expanded", String(expanded));
        button.setAttribute("aria-controls", id);
        button.title = `${expanded ? "Скрыть" : "Показать"}: ${name.toLowerCase()}`;
        const label = button.querySelector("[data-panel-label]");
        if (label) {
          label.textContent = id === "workspace-pages" ? "Страницы" : "Инспектор";
          button.setAttribute("aria-label", `${expanded ? "Скрыть" : "Показать"} ${label.textContent.toLowerCase()}`);
        }
      }
    }
  }

  function updateLayout() {
    const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui-scale")) || 1;
    const width = shell?.clientWidth ?? window.innerWidth;
    const compact = width < 1180 * scale;
    const nextSmall = width < 760 * scale;
    document.body.classList.toggle("is-compact-layout", compact);
    document.body.classList.toggle("is-small-layout", nextSmall);
    if (nextSmall && !small) {
      panels.forEach(({ cls }) => document.body.classList.add(cls));
    } else if (compact && panels.every(({ cls }) => !document.body.classList.contains(cls))) {
      document.body.classList.add("is-inspector-collapsed");
    }
    small = nextSmall;
    syncPanels();
  }

  updateLayout();
  // Размер тулбара меняется и при настройке масштаба интерфейса.
  const observer = new ResizeObserver(updateLayout);
  if (shell) observer.observe(shell);
  const toolbar = document.querySelector(".toolbar");
  if (toolbar) observer.observe(toolbar);

  document.addEventListener("click", (event) => {
    const panelBtn = event.target.closest("[data-toggle-panel]");
    if (panelBtn) {
      const cls = panelBtn.getAttribute("data-toggle-panel");
      if (panels.some((panel) => panel.cls === cls)) {
        const collapsed = document.body.classList.toggle(cls);
        if (!collapsed && document.body.classList.contains("is-compact-layout")) {
          panels.filter((panel) => panel.cls !== cls).forEach((panel) => document.body.classList.add(panel.cls));
        }
        syncPanels();
      }
      return;
    }

    const popBtn = event.target.closest("[data-pop-btn]");
    const insidePop = event.target.closest(".dock__pop, .pop");
    if (popBtn) {
      const id = popBtn.getAttribute("data-pop-btn");
      const pop = id ? document.getElementById(id) : null;
      if (pop) {
        closePops(pop);
        pop.hidden = !pop.hidden;
        popBtn.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
      }
      event.preventDefault();
      return;
    }
    if (!insidePop) closePops(null);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeShellPopover();
    }
  });
}

// Сначала закрыть временное управление; Escape не должен заодно отменять работу.
export function closeShellPopover() {
  const open = document.querySelectorAll(".dock__pop:not([hidden]), .pop:not([hidden])");
  if (!open.length) return false;
  const expanded = [...document.querySelectorAll("[data-pop-btn][aria-expanded='true']")];
  const trigger = expanded.find((button) => document.getElementById(button.getAttribute("data-pop-btn"))?.contains(document.activeElement)) || expanded[0];
  closePops(null);
  trigger?.focus();
  return true;
}

function closePops(except) {
  document.querySelectorAll(".dock__pop:not([hidden]), .pop:not([hidden])").forEach((pop) => {
    if (pop !== except) pop.hidden = true;
  });
  document.querySelectorAll("[data-pop-btn][aria-expanded='true']").forEach((btn) => {
    const target = document.getElementById(btn.getAttribute("data-pop-btn"));
    if (!target || target.hidden) btn.setAttribute("aria-expanded", "false");
  });
}
