/* Переключение разделов левой панели. */

export function initSidebarTabs(onBeforeSwitch = () => {}) {
  const tabs = [...document.querySelectorAll("[data-sidebar-tab]")];
  const panels = [...document.querySelectorAll("[data-sidebar-panel]")];
  if (tabs.length !== 2 || panels.length !== 2) return;

  const activate = (selected, focus = false) => {
    const id = selected.dataset.sidebarTab;
    onBeforeSwitch(id);
    tabs.forEach((tab) => {
      const active = tab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.sidebarPanel !== id;
    });
    if (focus) selected.focus();
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activate(tab));
    tab.addEventListener("keydown", (event) => {
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      activate(tabs[next], true);
    });
  });
}
