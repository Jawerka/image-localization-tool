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

  function visibleImageRect(box, naturalWidth, naturalHeight, objectFit, objectPosition) {
    const fit = String(objectFit || "fill");
    const nw = Number(naturalWidth) || 0;
    const nh = Number(naturalHeight) || 0;
    const width = Number(box.width) || 0;
    const height = Number(box.height) || 0;
    const left = Number(box.left) || 0;
    const top = Number(box.top) || 0;
    if (!nw || !nh || fit === "fill" || fit === "none" || fit === "scale-down") {
      return { left: left, top: top, width: width, height: height, right: left + width, bottom: top + height };
    }
    const scale = fit === "contain"
      ? Math.min(width / nw, height / nh)
      : Math.max(width / nw, height / nh);
    const drawnW = nw * scale;
    const drawnH = nh * scale;
    const parts = String(objectPosition || "50% 50%").trim().split(/\s+/);
    const parse = (token, size, drawn) => {
      const raw = token || "50%";
      if (raw.endsWith("%")) return (Number(raw.slice(0, -1)) || 0) / 100 * (size - drawn);
      return Number(raw) || 0;
    };
    const ox = parse(parts[0], width, drawnW);
    const oy = parse(parts[1] || parts[0], height, drawnH);
    const x = left + ox;
    const y = top + oy;
    return { left: x, top: y, width: drawnW, height: drawnH, right: x + drawnW, bottom: y + drawnH };
  }

  root.iltButtonModel = {
    stageLabel: stageLabel,
    redactUrl: redactUrl,
    formatEta: formatEta,
    pickCorner: pickCorner,
    visibleImageRect: visibleImageRect,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
