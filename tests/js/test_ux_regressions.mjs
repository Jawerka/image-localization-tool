import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const main = readFileSync(new URL('../../web/js/main.js', import.meta.url), 'utf8');
const dialogs = readFileSync(new URL('../../web/js/dialogs.js', import.meta.url), 'utf8');

test('Escape закрывает поповер раньше остановки обработки и сброса выделения', () => {
  const escape = main.slice(main.indexOf('function escape()'), main.indexOf('\nfunction onDrag('));
  let open = true;
  let stops = 0;
  let deselections = 0;
  const context = vm.createContext({
    menuOpen: () => false, closeTop: () => false, settingsOpen: () => false,
    isWizard: () => false, cancelPolylineDraft: () => false,
    closeShellPopover: () => { if (!open) return false; open = false; return true; },
    getState: () => ({ busy: true, selectedRegionId: 'r1' }),
    batchIsLive: () => true, stopJobs: () => stops++, selectRegion: () => deselections++,
  });
  vm.runInContext(escape, context);
  context.escape();
  assert.equal(open, false);
  assert.equal(stops, 0);
  assert.equal(deselections, 0);
  context.escape();
  assert.equal(stops, 1);
});

test('экспорт различает браузер и desktop; качество PNG отключено, JPG сохраняется', () => {
  let browser = true;
  const nodes = new Map();
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: '', hidden: false, parent: { hidden: false },
      closest() { return this.parent; },
    });
    return nodes.get(selector);
  }
  const quality = node("[data-role='export-quality']");
  const value = node("[data-role='export-quality-value']");
  const format = node("[data-role='export-format']");
  const folder = node("[data-role='export-dir']");
  const clash = node("input[name='export-clash']");
  const hint = node("[data-role='export-download-hint']");
  const settings = { export_format: 'png', export_jpeg_quality: 83 };
  const context = vm.createContext({
    document: { querySelector: node }, overlay: { querySelector: node },
    getState: () => ({ pages: [{ id: 'p', status: 'done' }], selectedPageIds: [], settings }),
    isReadyStatus: () => true, browserFiles: () => browser, setChoice() {}, show() {},
  });
  const start = dialogs.indexOf('export function openExport()');
  const end = dialogs.indexOf('export function openModelPick(');
  vm.runInContext('let dirReady;\n' + dialogs.slice(start, end).replace('export function', 'function'), context);
  context.openExport();
  assert.equal(folder.parent.hidden, true);
  assert.equal(clash.parent.hidden, true);
  assert.equal(hint.hidden, false);
  assert.equal(quality.disabled, true);
  assert.equal(value.textContent, '—');
  format.value = 'jpg'; context.syncExportQuality();
  assert.equal(quality.disabled, false);
  assert.equal(value.textContent, '83');
  browser = false; settings.export_format = 'jpg'; context.openExport();
  assert.equal(folder.parent.hidden, false);
  assert.equal(clash.parent.hidden, false);
  assert.equal(hint.hidden, true);
  assert.equal(quality.disabled, false);
});
