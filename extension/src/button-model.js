// Подписи кнопки и обезличивание адресов. Без API браузера, чтобы проверять из Node.
(function (root) {
  "use strict";

  const STAGE = {
    detect: "Ищем текст",
    load: "Ищем текст",
    ocr: "Распознаём",
    translate: "Переводим",
    segment: "Стираем оригинал",
    inpaint: "Стираем оригинал",
    typeset: "Вписываем перевод",
    cache: "Из кэша",
  };

  function stageLabel(stage, serverLabel, fromCache) {
    if (fromCache) return "Из кэша";
    const code = String(stage || "");
    if (STAGE[code]) return STAGE[code];
    const text = String(serverLabel || "").trim();
    if (text && STAGE[text]) return STAGE[text];
    if (text && text !== code) return text;
    return "Переводим";
  }

  function redactUrl(value) {
    const raw = String(value || "");
    try {
      const url = new URL(raw);
      url.search = "";
      url.hash = "";
      return url.toString();
    } catch (_) {
      return raw.split("#")[0].split("?")[0];
    }
  }

  function formatEta(ms) {
    if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 5000) return "";
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return seconds + " с";
    return Math.ceil(seconds / 60) + " мин";
  }

  function pickCorner(blocked) {
    const order = ["tr", "tl", "br", "bl"];
    for (let i = 0; i < order.length; i += 1) {
      if (!blocked || !blocked[order[i]]) return order[i];
    }
    return "tr";
  }

  root.iltButtonModel = { stageLabel: stageLabel, redactUrl: redactUrl, formatEta: formatEta, pickCorner: pickCorner };
})(typeof globalThis !== "undefined" ? globalThis : this);
