import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.attrs = {};
    this.children = [];
    this.parentElement = null;
    this.isConnected = true;
    this.listeners = { load: [], error: [] };
    this.complete = true;
    this.naturalWidth = 100;
    this.naturalHeight = 50;
    this.currentSrc = "";
    this._src = "";
  }
  closest(sel) {
    if (sel === "picture" && this.parentElement?.tagName === "PICTURE") return this.parentElement;
    return null;
  }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }
  getAttribute(name) { return this.hasAttribute(name) ? this.attrs[name] : null; }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === "src") {
      this._src = String(value);
      this.currentSrc = String(value);
    }
    this.observer?.notify();
  }
  removeAttribute(name) {
    delete this.attrs[name];
    if (name === "src") { this._src = ""; this.currentSrc = ""; }
    this.observer?.notify();
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(item => item !== fn); }
  get src() { return this._src; }
  set src(value) {
    this._src = String(value);
    this.currentSrc = String(value);
    this.attrs.src = String(value);
    queueMicrotask(() => { for (const fn of this.listeners.load || []) fn(); });
    this.observer?.notify();
  }
  decode() { return Promise.resolve(); }
}

class FakeObserver {
  constructor(callback) { this.callback = callback; this.nodes = []; }
  observe(node) { node.observer = this; this.nodes.push(node); }
  disconnect() { for (const node of this.nodes) if (node.observer === this) node.observer = null; }
  notify() { queueMicrotask(() => this.callback([])); }
}

function loadSwap() {
  let urls = 0;
  const blobs = new Map();
  const events = [];
  const context = vm.createContext({
    queueMicrotask,
    URL: class {
      constructor(value, base) { this.href = String(value).includes("://") ? String(value) : `${base || "http://127.0.0.1/"}${String(value).replace(/^\//, "")}`; }
      static createObjectURL(blob) {
        urls += 1;
        const url = `blob:test-${urls}`;
        blobs.set(url, blob);
        return url;
      }
      static revokeObjectURL(url) { blobs.delete(url); }
    },
    Image: class {
      constructor() { this.naturalWidth = 100; this.naturalHeight = 50; this.src = ""; }
      async decode() {}
    },
    document: { baseURI: "http://127.0.0.1/", createElement: () => ({ getContext() { return { drawImage() {} }; }, toBlob(cb) { cb(new Blob(["x"])); } }) },
    MutationObserver: FakeObserver,
    createImageBitmap: async () => ({ width: 100, height: 50, close() {} }),
    OffscreenCanvas: class {
      constructor() {}
      getContext() { return { drawImage() {} }; }
      convertToBlob() { return Promise.resolve(new Blob(["png"])); }
    },
    globalThis: {},
  });
  context.globalThis = context;
  vm.runInContext(readFileSync(new URL("../../extension/src/native-swap.js", import.meta.url), "utf8"), context);
  context.iltNativeSwap.onChange(event => events.push(event));
  return { swap: context.iltNativeSwap, events, blobs };
}

function makeImg() {
  const img = new FakeNode("IMG");
  img.src = "http://127.0.0.1/pic.png";
  img.attrs.src = "http://127.0.0.1/pic.png";
  img.currentSrc = "http://127.0.0.1/pic.png";
  return img;
}

test("подмена ставит srcset с плотностью 1x и откатывает отсутствие атрибутов", async () => {
  const { swap } = loadSwap();
  const img = makeImg();
  const blob = new Blob(["png"]);
  const applied = await swap.apply(img, blob);
  assert.equal(applied.ok, true);
  assert.match(img.getAttribute("srcset"), /blob:test-1 1x/);
  assert.equal(img.hasAttribute("sizes"), false);
  swap.restore(img);
  assert.equal(img.getAttribute("src"), "http://127.0.0.1/pic.png");
  assert.equal(img.hasAttribute("srcset"), false);
});

test("сайт вернул оригинал — перевод ставится снова, после лимита fallback", async () => {
  const { swap, events } = loadSwap();
  const img = makeImg();
  await swap.apply(img, new Blob(["png"]));
  for (let i = 0; i < 4; i += 1) {
    img.removeAttribute("srcset");
    img.src = "http://127.0.0.1/pic.png";
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  assert.ok(events.some(event => event.type === "fallback"));
});

test("picture с source не подменяется — вызывающий рисует overlay", async () => {
  const { swap } = loadSwap();
  const picture = new FakeNode("PICTURE");
  const source = new FakeNode("SOURCE");
  const img = makeImg();
  source.setAttribute("type", "image/webp");
  source.setAttribute("srcset", "http://127.0.0.1/pic.webp");
  picture.children = [source, img];
  source.parentElement = picture;
  img.parentElement = picture;
  const applied = await swap.apply(img, new Blob(["png"]));
  assert.equal(applied.ok, false);
  assert.match(applied.error, /picture/);
  assert.equal(img.src, "http://127.0.0.1/pic.png");
  assert.equal(source.getAttribute("type"), "image/webp");
  assert.equal(swap.isSwapped(img), false);
});

test("новый URL не откатывается поверх сайта и шлёт new-image", async () => {
  const { swap, events } = loadSwap();
  const img = makeImg();
  await swap.apply(img, new Blob(["png"]));
  img.removeAttribute("srcset");
  img.src = "http://127.0.0.1/other.png";
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(swap.isSwapped(img), false);
  assert.equal(img.src, "http://127.0.0.1/other.png");
  assert.equal(events.at(-1)?.type, "new-image");
  assert.equal(events.at(-1)?.url, "http://127.0.0.1/other.png");
});
