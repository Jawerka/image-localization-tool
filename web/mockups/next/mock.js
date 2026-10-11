/* Общий скрипт макетов v2: тема/масштаб из URL и localStorage,
   демонстрационные переключения панелей, доков, табов и поповеров.
   Не имеет отношения к живому UI. */

(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var theme = params.get("theme") || "";
  var scale = "";

  try {
    if (!theme) theme = localStorage.getItem("ilt-next-theme") || "";
    scale = params.get("scale") || localStorage.getItem("ilt-next-scale") || "";
  } catch (err) {
    /* localStorage может быть недоступен на file:// */
  }

  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  }

  var n = parseInt(scale, 10);
  if (n >= 100 && n <= 150 && n !== 100) {
    document.documentElement.style.zoom = String(n / 100);
  }

  function closePops(except) {
    document.querySelectorAll(".pop:not([hidden])").forEach(function (pop) {
      if (pop !== except) pop.hidden = true;
    });
    document.querySelectorAll("[data-pop-btn][aria-expanded='true']").forEach(function (btn) {
      var target = document.getElementById(btn.getAttribute("data-pop-btn"));
      if (!target || target.hidden) btn.setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("click", function (event) {
    var popBtn = event.target.closest("[data-pop-btn]");
    var insidePop = event.target.closest(".pop");

    if (popBtn) {
      var pop = document.getElementById(popBtn.getAttribute("data-pop-btn"));
      if (pop) {
        closePops(pop);
        pop.hidden = !pop.hidden;
        popBtn.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
      }
      event.preventDefault();
      return;
    }

    if (!insidePop) {
      closePops(null);
    }

    var panelBtn = event.target.closest("[data-toggle-panel]");
    if (panelBtn) {
      document.body.classList.toggle(panelBtn.getAttribute("data-toggle-panel"));
      return;
    }

    var radio = event.target.closest("[data-radiogroup] [role='radio']");
    if (radio) {
      radio.closest("[data-radiogroup]").querySelectorAll("[role='radio']").forEach(function (btn) {
        btn.setAttribute("aria-checked", btn === radio ? "true" : "false");
      });
      return;
    }

    var tab = event.target.closest("[data-tabs] [role='tab']");
    if (tab) {
      var root = tab.closest("[data-tabs]");
      root.querySelectorAll("[role='tab']").forEach(function (btn) {
        btn.setAttribute("aria-selected", btn === tab ? "true" : "false");
      });
      root.querySelectorAll("[data-tabpanel]").forEach(function (panel) {
        panel.hidden = panel.getAttribute("data-tabpanel") !== tab.getAttribute("data-tab");
      });
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closePops(null);
  });
})();
