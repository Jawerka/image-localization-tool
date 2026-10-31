// Клиент журнала: страница, пульт и настройки шлют пачки в фон.
(() => {
  "use strict";
  const ext = globalThis.chrome ?? globalThis.browser;
  const buffer = [];
  let timer = 0;

  function send(message) {
    if (!ext?.runtime?.sendMessage) return Promise.resolve(null);
    return new Promise((resolve) => {
      try {
        let settled = false;
        const finish = (value) => {
          if (settled) return;
          settled = true;
          resolve(value);
        };
        const response = ext.runtime.sendMessage(message, (value) => {
          const error = ext.runtime.lastError;
          finish(error ? null : value);
        });
        if (response?.then) response.then((value) => { if (value !== undefined) finish(value); }, () => finish(null));
      } catch (_) {
        resolve(null);
      }
    });
  }

  function flush() {
    if (!buffer.length) return;
    const entries = buffer.splice(0, buffer.length);
    void send({ type: "log-write", entries: entries });
  }

  function write(partial) {
    const entry = partial && typeof partial === "object" ? partial : { msg: String(partial || "") };
    buffer.push({
      t: Date.now(),
      lvl: entry.lvl || "info",
      src: entry.src || "page",
      tab: entry.tab ?? null,
      ev: entry.ev || "",
      msg: String(entry.msg || ""),
      data: entry.data && typeof entry.data === "object" ? entry.data : {},
    });
    if (buffer.length >= 20) flush();
    else if (!timer) timer = setTimeout(() => { timer = 0; flush(); }, 400);
  }

  globalThis.iltLog = {
    write: write,
    flush: flush,
    save: () => send({ type: "log-save" }),
    copy: () => send({ type: "log-copy" }),
    clear: () => send({ type: "log-clear" }),
    setVerbose: (on) => send({ type: "log-verbose", on: !!on }),
    verbose: () => send({ type: "log-verbose-get" }),
  };
})();
