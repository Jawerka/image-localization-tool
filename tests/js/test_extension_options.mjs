import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

test("отложенная загрузка адреса не отменяет сопряжение", async () => {
  const elements = new Map();
  const element = id => {
    if (id === "pair-cells") return null;
    if (!elements.has(id)) elements.set(id, { value: "", addEventListener() {} });
    return elements.get(id);
  };
  let loaded;
  const requests = [];
  const context = vm.createContext({
    document: { getElementById: element, documentElement: { dataset: {} } },
    chrome: { runtime: {}, storage: { local: {
      get(keys, callback) {
        if (keys === "serverUrl") loaded = callback;
        else callback({});
      },
      set(_items, callback) { callback(); },
    } } },
    fetch: async (url, options) => {
      requests.push([url, options?.method]);
      return { ok: true, status: 200, json: async () => ({ token: "paired" }) };
    },
  });
  vm.runInContext(readFileSync(new URL("../../extension/src/options.js", import.meta.url), "utf8"), context);
  await vm.runInContext('pair("http://127.0.0.1:12345", "123456")', context);
  loaded({ serverUrl: "http://127.0.0.1:8765" });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(element("status").textContent, "сопряжено");
  assert.deepEqual(requests, [["http://127.0.0.1:12345/v1/pair", "POST"]]);
});
