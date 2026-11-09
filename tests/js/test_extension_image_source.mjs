import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../../extension/src/image-source.js", import.meta.url), "utf8");
const imageUrl = "https://image.example/original.webp?secret=private";

function reader(overrides = {}) {
  const logs = [];
  const calls = [];
  let canvas;
  const node = { tagName: "IMG", complete: true, naturalWidth: 1280, naturalHeight: 1808, currentSrc: imageUrl, src: imageUrl, isConnected: true };
  const context = vm.createContext({
    Blob, Uint8Array, AbortController, setTimeout, clearTimeout, btoa,
    fetch: async (url, options) => { calls.push({ url, options }); return new Response("original", {headers:{"content-type":"image/webp"}}); },
    document: { createElement: () => (canvas = { width: 0, height: 0,
      getContext: () => ({ drawImage: image => assert.equal(image, node) }),
      toBlob: callback => callback(new Blob(["pixels"], {type:"image/png"})),
    }) },
    ...overrides,
  });
  vm.runInContext(source, context);
  return { context, node, calls, logs, canvas: () => canvas,
    read: (choice = {}) => context.iltImageSource.read({url:imageUrl, node, ...choice}, (...args) => logs.push(args)),
  };
}

test("Страница читает исходные байты с force-cache, затем передаёт их без потерь", async () => {
  const r = reader();
  const result = await r.read();
  assert.equal(atob(result.imageBase64), "original");
  assert.equal(result.imageMime, "image/webp");
  assert.equal(r.calls[0].options.cache, "force-cache");
  assert.equal(r.calls[0].options.credentials, "same-origin");
  assert.equal(r.canvas(), undefined);
  assert.equal(JSON.stringify(r.logs).includes("private"), false);
});

test("Сбой fetch использует пиксели загруженного оригинала и освобождает canvas", async () => {
  const r = reader({fetch: async () => { throw new TypeError("Failed to fetch"); }});
  const result = await r.read();
  assert.equal(atob(result.imageBase64), "pixels");
  assert.equal(result.imageMime, "image/png");
  const picked = r.logs.find(row => row[0] === "image-source")[2];
  assert.equal(picked.width, 1280);
  assert.equal(picked.height, 1808);
  assert.equal(r.canvas().width, 0);
});

test("Защищённый canvas оставляет запасную загрузку и не раскрывает URL", async () => {
  const r = reader({
    fetch: async () => { throw new TypeError("blocked"); },
    document: {createElement: () => ({ getContext: () => ({drawImage() {}}), toBlob() { throw new DOMException("tainted", "SecurityError"); } })},
  });
  assert.deepEqual(Object.keys(await r.read()), []);
  assert.equal(r.logs.at(-1)[2].name, "SecurityError");
  assert.equal(JSON.stringify(r.logs).includes("private"), false);
});

test("Непрозрачный, пустой, HTTP-ошибка и не-картинка не выдаются за исходные байты", async () => {
  for (const response of [
    {ok:false,status:0,type:"opaque"},
    new Response("", {headers:{"content-type":"image/png"}}),
    new Response("denied", {status:403}),
    new Response("<html>oops</html>", {headers:{"content-type":"text/html"}}),
  ]) {
    const r = reader({fetch:async () => response});
    r.node.complete = false;
    assert.deepEqual(Object.keys(await r.read()), []);
  }
});

test("Смена src при чтении и переведённая blob-подмена не дают чужие пиксели", async () => {
  let r = reader();
  r.context.fetch = async () => {
    r.node.currentSrc = "https://image.example/other.png";
    return new Response("old", {headers:{"content-type":"image/png"}});
  };
  assert.deepEqual(Object.keys(await r.read()), []);
  r = reader({fetch:async () => { throw new TypeError("offline"); }});
  r.node.currentSrc = "blob:https://image.example/translated";
  assert.deepEqual(Object.keys(await r.read()), []);
  assert.equal(r.canvas(), undefined);
});

test("Таймаут страницы отменяет fetch и чтение тела, затем даёт fallback", async () => {
  for (const stalledBody of [false, true]) {
    let abort;
    let timeout;
    const r = reader({
      setTimeout: (callback, delay) => { abort = callback; timeout = delay; return 1; },
      clearTimeout() {},
      fetch: async (_url, options) => {
        const pending = () => new Promise((_resolve,reject) => {
          const fail = () => reject(new DOMException("timeout", "AbortError"));
          if (options.signal.aborted) fail();
          else options.signal.addEventListener("abort", fail);
        });
        return stalledBody ? {ok:true,blob:pending} : pending();
      },
    });
    r.node.complete = false;
    const task = r.read();
    await Promise.resolve();
    abort();
    assert.deepEqual(Object.keys(await task), []);
    assert.equal(timeout, 5000);
    assert.equal(r.logs[0][2].name, "AbortError");
  }
});

test("blob/data и явно переданные байты сохраняют поддержку", async () => {
  const r = reader();
  for (const url of ["blob:https://site.example/original", "data:image/png;base64,YQ=="]) {
    assert.equal(atob((await r.read({url, node:null})).imageBase64), "original");
  }
  assert.equal((await r.read({imageBase64:"YQ==",imageMime:"image/png"})).imageBase64, "YQ==");
});

test("Картинка больше 32 МиБ не раздувает сообщение и идёт запасным путём", async () => {
  const r = reader({fetch:async () => ({ok:true,blob:async () => ({size:33*1024*1024})})});
  r.node.complete = false;
  assert.deepEqual(Object.keys(await r.read()), []);
  assert.equal(r.logs[0][2].code, "E_INLINE_SIZE");
});
