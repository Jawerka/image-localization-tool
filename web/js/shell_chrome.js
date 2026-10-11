/* Панели, поповеры дока — оболочка v2. */

export function initShellChrome() {
  document.addEventListener("click", (event) => {
    const panelBtn = event.target.closest("[data-toggle-panel]");
    if (panelBtn) {
      const cls = panelBtn.getAttribute("data-toggle-panel");
      if (cls) document.body.classList.toggle(cls);
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
    if (event.key === "Escape") closePops(null);
  });
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
