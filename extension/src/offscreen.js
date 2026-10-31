"use strict";

const ext = globalThis.chrome ?? globalThis.browser;

if (ext && ext.runtime && ext.runtime.onMessage) {
  ext.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "offscreen-play") return undefined;
    const api = globalThis.iltChime;
    const task = api ? api.play(message.chimeId, message.chimeVolume) : Promise.reject(new Error("нет сигнала"));
    Promise.resolve(task).then(
      () => sendResponse({ ok: true }),
      () => sendResponse({ ok: false }),
    );
    return true;
  });
}
