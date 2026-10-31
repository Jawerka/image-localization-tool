import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../web/js/main.js', import.meta.url), 'utf8');
const render = source.slice(source.indexOf('function renderBanners('), source.indexOf('\nfunction renderRecent('));
function setup() {
  let now = 0;
  let serial = 0;
  const timers = new Map();
  const host = { innerHTML: '' };
  const state = { booted: true, banners: [], dismissed: new Set() };
  const context = vm.createContext({
    document: { querySelector: () => host },
    setTimeout(fn, delay) { const id = ++serial; timers.set(id, { fn, at: now + delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    queueMicrotask() {},
    isBannerDismissed: (id) => state.dismissed.has(id),
    dismissBanner(id) { state.dismissed.add(id); state.banners = state.banners.filter(b => b.id !== id); draw(); },
    escapeText: (s) => s, icon: () => '',
  });
  vm.runInContext('let bannerMarkup = ""; const bannerTimers = new Map();\n' + render, context);
  function draw() { context.renderBanners(state); }
  function advance(ms) {
    now += ms;
    for (const [id, entry] of [...timers]) {
      if (entry.at <= now && timers.has(id)) { timers.delete(id); entry.fn(); }
    }
  }
  return { state, host, timers, draw, advance };
}

test('баннеры исчезают независимо через 5000 мс; обновления не продлевают срок', () => {
  const h = setup();
  h.state.banners = [{ id: 'a', text: 'Первый' }]; h.draw();
  h.advance(3000); h.draw();
  h.state.banners.push({ id: 'b', text: 'Второй' }); h.draw();
  h.advance(1999); assert.match(h.host.innerHTML, /Первый/);
  h.advance(1); assert.doesNotMatch(h.host.innerHTML, /Первый/); assert.match(h.host.innerHTML, /Второй/);
  h.advance(3000); assert.equal(h.host.innerHTML, ''); assert.equal(h.timers.size, 0);
});

test('удаление, замена и сброс загрузки отменяют прежний таймер', () => {
  const h = setup();
  h.state.banners = [{ id: 'a', text: 'Старый' }]; h.draw(); h.advance(4000);
  h.state.banners = [{ id: 'a', text: 'Новый' }]; h.draw(); h.advance(1000);
  assert.match(h.host.innerHTML, /Новый/);
  h.state.banners = []; h.draw(); assert.equal(h.timers.size, 0);
  h.state.banners = [{ id: 'a', text: 'Снова' }]; h.draw();
  h.state.booted = false; h.draw(); assert.equal(h.timers.size, 0);
  h.state.booted = true; h.draw(); assert.match(h.host.innerHTML, /Снова/);
});

test('системный баннер после автозакрытия не возвращается при обновлении', () => {
  const h = setup(); h.state.llm = { ok: false }; h.draw(); h.advance(5000); h.draw();
  assert.equal(h.host.innerHTML, ''); assert.equal(h.timers.size, 0);
});
