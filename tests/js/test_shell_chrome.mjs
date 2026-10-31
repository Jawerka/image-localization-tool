import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { initShellChrome } from '../../web/js/shell_chrome.js';

test('shell chrome markup keeps floating dock and smoke data-roles', () => {
  const html = readFileSync(new URL('../../web/index.html', import.meta.url), 'utf8');
  assert.match(html, /data-role="tool-dock"/);
  assert.match(html, /viewer__bar dock/);
  assert.match(html, /data-toggle-panel="is-pages-collapsed"/);
  assert.match(html, /data-toggle-panel="is-inspector-collapsed"/);
  assert.match(html, /data-role="tool-brush"/);
  assert.match(html, /data-role="apply-edits"/);
  assert.match(html, /shell-v2\.css/);
  assert.doesNotMatch(html, /class="workspace-controls"/);
  const footer = html.slice(html.indexOf('<footer class="statusbar"'), html.indexOf('</footer>'));
  assert.equal((footer.match(/data-panel-label/g) || []).length, 2);
  assert.match(footer, /data-panel-label>Страницы/);
  assert.match(footer, /data-panel-label>Инспектор/);
});

// Минимальный DOM проверяет переходы состояния, фокус и изменение ширины.
function setup(width = 1280) {
  const classes = new Set();
  const classList = {
    contains: (name) => classes.has(name),
    add: (name) => classes.add(name),
    toggle(name, force = !classes.has(name)) {
      if (force) classes.add(name); else classes.delete(name);
      return force;
    },
  };
  const listeners = {};
  const shell = { clientWidth: width };
  const toolbar = {};
  let observed;
  let scale = 1;
  const doc = {
    body: { classList }, documentElement: {}, activeElement: null,
    addEventListener: (name, callback) => { listeners[name] = callback; },
  };
  const panels = ['pages', 'inspector'].map((name) => ({
    id: `workspace-${name}`, inert: false, attrs: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    contains: (element) => element?.panel === name,
  }));
  const pop = { id: 'test-pop', hidden: true, contains: (el) => el?.popover };
  function button(attrs, top = true) {
    return {
      label: top ? { textContent: '' } : null,
      querySelector() { return this.label; },
      attrs, getAttribute(key) { return this.attrs[key] ?? null; },
      setAttribute(key, value) { this.attrs[key] = value; },
      closest(selector) {
        if (selector === '.workspace-controls') return top ? toolbar : null;
        if (selector === '[data-toggle-panel]') return this.attrs['data-toggle-panel'] ? this : null;
        if (selector === '[data-pop-btn]') return this.attrs['data-pop-btn'] ? this : null;
        return null;
      },
      focus() { doc.activeElement = this; },
    };
  }
  const buttons = ['pages', 'inspector'].flatMap((name) => [
    button({ 'data-toggle-panel': `is-${name}-collapsed` }),
    button({ 'data-toggle-panel': `is-${name}-collapsed` }, false),
  ]);
  const trigger = button({ 'data-pop-btn': pop.id });
  doc.getElementById = (id) => [...panels, pop].find((el) => el.id === id);
  doc.querySelector = (selector) => selector === '.toolbar' ? toolbar : shell;
  doc.querySelectorAll = (selector) => {
    if (selector.startsWith('[data-toggle-panel=')) {
      return buttons.filter((b) => selector.includes(b.attrs['data-toggle-panel']));
    }
    if (selector.includes('[data-pop-btn]')) return trigger.attrs['aria-expanded'] === 'true' ? [trigger] : [];
    return pop.hidden ? [] : [pop];
  };
  const saved = ['document', 'window', 'ResizeObserver', 'getComputedStyle'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
  Object.assign(globalThis, {
    document: doc, window: { innerWidth: width },
    ResizeObserver: class { constructor(fn) { observed = fn; } observe() {} },
    getComputedStyle: () => ({ getPropertyValue: () => String(scale) }),
  });
  initShellChrome();
  return {
    doc, panels, buttons, pop, trigger, classes,
    click(target) { listeners.click({ target, preventDefault() {} }); },
    escape() { listeners.keydown({ key: 'Escape' }); },
    resize(value, nextScale = scale) { shell.clientWidth = value; scale = nextScale; observed(); },
    restore() { for (const [key, descriptor] of saved) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key]; } },
  };
}

test('панели доступны со старта, дубли кнопок синхронны, скрытая панель не получает фокус', () => {
  const h = setup();
  try {
    assert.deepEqual(h.panels.map((p) => p.inert), [false, false]);
    assert.equal(h.buttons[0].label.textContent, 'Страницы');
    assert.equal(h.buttons[2].label.textContent, 'Инспектор');
    assert.equal(h.buttons[0].attrs['aria-label'], 'Скрыть страницы');
    h.doc.activeElement = { panel: 'pages' };
    h.click(h.buttons[1]);
    assert.equal(h.panels[0].inert, true);
    assert.equal(h.panels[0].attrs['aria-hidden'], 'true');
    assert.equal(h.doc.activeElement, h.buttons[0]);
    assert.equal(h.buttons[0].label.textContent, 'Страницы');
    assert.equal(h.buttons[0].attrs['aria-label'], 'Показать страницы');
    assert.deepEqual(h.buttons.slice(0, 2).map((b) => b.attrs['aria-expanded']), ['false', 'false']);
    h.click(h.buttons[0]);
    assert.equal(h.panels[0].inert, false);
    assert.equal(h.buttons[0].label.textContent, 'Страницы');
    assert.equal(h.buttons[0].attrs['aria-label'], 'Скрыть страницы');
    assert.equal(h.buttons[0].attrs['aria-controls'], 'workspace-pages');
  } finally { h.restore(); }
});

test('компактный режим открывает одну панель и учитывает масштаб без сброса ручного выбора', () => {
  const h = setup(1024);
  try {
    assert.deepEqual(h.panels.map((p) => p.inert), [false, true]);
    h.click(h.buttons[2]);
    assert.deepEqual(h.panels.map((p) => p.inert), [true, false]);
    h.resize(1400);
    assert.deepEqual(h.panels.map((p) => p.inert), [true, false]);
    h.click(h.buttons[0]);
    assert.deepEqual(h.panels.map((p) => p.inert), [false, false]);
    h.resize(1400, 1.5);
    assert.deepEqual(h.panels.map((p) => p.inert), [false, true]);
    h.resize(600);
    assert.deepEqual(h.panels.map((p) => p.inert), [true, true]);
    h.click(h.buttons[0]); h.resize(600);
    assert.deepEqual(h.panels.map((p) => p.inert), [false, true]);
  } finally { h.restore(); }
});

test('поповер закрывается Escape с возвратом фокуса и закрывается повторным нажатием', () => {
  const h = setup();
  try {
    h.click(h.trigger);
    assert.equal(h.pop.hidden, false);
    h.doc.activeElement = { popover: true };
    h.escape();
    assert.equal(h.pop.hidden, true);
    assert.equal(h.trigger.attrs['aria-expanded'], 'false');
    assert.equal(h.doc.activeElement, h.trigger);
    h.click(h.trigger); h.click(h.trigger);
    assert.equal(h.pop.hidden, true);
  } finally { h.restore(); }
});
