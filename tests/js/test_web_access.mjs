import { test } from 'node:test';
import assert from 'node:assert/strict';
import { patch } from '../../web/js/state.js';
import { clearAccessSecrets, initAccessSettings, refreshAccessSettings } from '../../web/js/web_access.js';
import { connectEvents } from '../../web/js/api.js';

test('настройки доступа: открытый режим, несовпадение паролей, сохранение и очистка секретов', async () => {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { value: '', checked: false, hidden: false, disabled: false,
      textContent: '', handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }, focus() {} });
    return elements.get(id);
  };
  const originalDocument = globalThis.document;
  const originalFetch = globalThis.fetch;
  globalThis.document = { getElementById: element };
  let requestBody;
  let saves = 0;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/browser/access');
    if (options.method === 'PUT') { saves++; requestBody = JSON.parse(options.body); }
    return { ok: true, text: async () => JSON.stringify(options.method === 'GET'
      ? { enabled: false, configured: false, username: '' }
      : { enabled: true, configured: true, username: requestBody.username }) };
  };
  try {
    patch({ capabilities: { browser_files: true } });
    initAccessSettings();
    await refreshAccessSettings();
    assert.equal(element('nav-access').hidden, false);
    assert.equal(element('access-enabled').checked, false);
    assert.equal(element('access-save').disabled, false);
    element('access-username').value = 'owner';
    element('access-password').value = 'my-password-059';
    element('access-confirm').value = 'different';
    await element('access-save').handlers.click();
    assert.equal(saves, 0);
    assert.equal(element('access-message').textContent, 'Пароли не совпадают');
    element('access-enabled').checked = true;
    element('access-confirm').value = 'my-password-059';
    await element('access-save').handlers.click();
    assert.equal(saves, 1);
    assert.equal(requestBody.username, 'owner');
    assert.equal(requestBody.enabled, true);
    assert.equal(element('access-password').value, '');
    assert.equal(element('access-current-row').hidden, false);
    assert.equal(element('access-save').disabled, false);
    element('access-current').value = 'my-password-059';
    clearAccessSecrets();
    assert.equal(element('access-current').value, '');
    patch({ capabilities: {} });
    await refreshAccessSettings();
    assert.equal(element('nav-access').hidden, true);
  } finally {
    globalThis.document = originalDocument;
    globalThis.fetch = originalFetch;
  }
});

test('отозванная SSE-сессия запрашивает вход вместо бесконечного переподключения', async () => {
  const saved = { window: globalThis.window, EventSource: globalThis.EventSource, fetch: globalThis.fetch };
  const sources = [];
  const events = [];
  let retries = 0;
  globalThis.window = { clearTimeout() {}, setTimeout() { retries++; return 1; } };
  globalThis.EventSource = class {
    constructor() { sources.push(this); }
    addEventListener() {}
    close() { this.closed = true; }
  };
  globalThis.fetch = async () => ({ ok: false, status: 401, text: async () => '{"error":"Не авторизован"}' });
  try {
    const dispose = connectEvents((name) => events.push(name));
    await sources[0].onerror();
    assert.deepEqual(events, ['session.required']);
    assert.equal(sources[0].closed, true);
    assert.equal(retries, 0);
    dispose();
  } finally { Object.assign(globalThis, saved); }
});
