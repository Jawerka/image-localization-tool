import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

function background(withPanel = true, granted = true) {
  const state = {};
  const events = [];
  const chrome = {
    runtime: { onMessage: { addListener() {} }, onInstalled: { addListener() {} }, getURL: path => `chrome-extension://test/${path}` },
    storage: {
      local: { get: async () => ({ serverUrl: "http://127.0.0.1:8765", token: "", targetLang: "ru" }), set: async () => {} },
      session: { set: async values => Object.assign(state, values), get: async key => ({ [key]: state[key] }) },
    },
    contextMenus: { create: async () => {}, removeAll: async () => {}, onClicked: { addListener() {} } },
    permissions: {
      request: async details => { events.push(["permission", details]); return granted; },
      contains: async () => granted,
    },
    tabs: { create: async options => { events.push(["tab", options]); }, sendMessage: async (...args) => { events.push(["inline", ...args]); return args[1]?.type === "inline-save" ? { ok: true, imageUrl: args[1].srcUrl, pageUrl: "https://site.example/" } : { ok: true }; } },
    downloads: { download: async options => { events.push(["download", options]); return 1; } },
  };
  if (withPanel) chrome.sidePanel = { open: async options => { events.push(["panel", options]); } };
  const context = vm.createContext({ chrome, queueMicrotask, setTimeout, URL });
  vm.runInContext(readFileSync(new URL("../../extension/src/background.js", import.meta.url), "utf8"), context);
  return { context, events, state };
}

test("ПКМ доставляет перевод в исходный frame без открытия панели", async () => {
  const { context, events, state } = background();
  vm.runInContext(`onContextMenuClick({menuItemId:'ilt-translate-image',srcUrl:'https://img.example/large.png',frameUrl:'https://frame.example/page',frameId:9},{id:0,windowId:7,url:'https://site.example'})`, context);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(events[0][0], "inline");
  assert.equal(state["selection:0"].imageUrl, "https://img.example/large.png");
  assert.equal(state["selection:0"].pageUrl, "https://frame.example/page");
  const delivery = events.find(event => event[0] === "inline");
  assert.equal(delivery[1], 0);
  assert.equal(delivery[2].type, "translate-inline");
  assert.equal(delivery[2].permitted, true);
  assert.equal(delivery[3].frameId, 9);
  assert.equal(events.some(event => ["tab", "panel"].includes(event[0])), false);
});

test("Боковая панель больше не открывается", async () => {
  const { context, events } = background(false);
  await vm.runInContext("openPanel(42, 7)", context);
  assert.equal(events.some(event => event[0] === "tab" || event[0] === "panel"), false);
});

test("Отказ в разрешении сохраняет выбор для панели и не запускает задачу", async () => {
  const { context, state, events } = background(true, false);
  vm.runInContext(`onContextMenuClick({menuItemId:'ilt-translate-image',srcUrl:'https://img.example/a.png',pageUrl:'https://site.example'},{id:5,windowId:7})`, context);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(state["selection:5"].imageUrl, "https://img.example/a.png");
  const result = await vm.runInContext(`handleGetStatus({pageUrl:'https://site.example',imageUrl:'https://img.example/a.png'})`, context);
  assert.equal(result.status, "idle");
  assert.equal(events.find(event => event[0] === "inline")[2].permitted, false);
});

test("ключ кэша различает язык и URL картинки", () => {
  const { context } = background();
  const ru = vm.runInContext(`resultCacheUrl('https://img.example/a.png', 'ru')`, context);
  const en = vm.runInContext(`resultCacheUrl('https://img.example/a.png', 'en')`, context);
  const other = vm.runInContext(`resultCacheUrl('https://img.example/b.png', 'ru')`, context);
  assert.notEqual(ru, en);
  assert.notEqual(ru, other);
  const pageA = vm.runInContext(`cacheKey('https://site.example/p1', 'https://img.example/a.png')`, context);
  const pageB = vm.runInContext(`cacheKey('https://site.example/p2', 'https://img.example/a.png')`, context);
  assert.notEqual(pageA, pageB);
});

test("force создаёт новую задачу, повтор без force не дублирует running", () => {
  const { context } = background();
  vm.runInContext(`
    const url = 'https://img.example/force-' + Date.now() + '.png';
    const first = reserveJob('https://site.example/force', url, false);
    const again = reserveJob('https://site.example/force', url, false);
    globalThis._created = Boolean(first.created && !again.created && first.job === again.job);
    first.job.status = 'running';
    const forced = reserveJob('https://site.example/force', url, true);
    globalThis._forced = Boolean(forced.created === true && forced.job.fresh === true);
  `, context);
  assert.equal(Boolean(vm.runInContext("_created", context)), true);
  assert.equal(Boolean(vm.runInContext("_forced", context)), true);
});

test("resumeStoredJobs не дублирует задачу с тем же ключом", async () => {
  const { context, state } = background();
  const key = vm.runInContext(`cacheKey('https://site.example/', 'https://img.example/a.png')`, context);
  state.iltJobs = [{
    key,
    pageUrl: "https://site.example/",
    imageUrl: "https://img.example/a.png",
    targetLang: "en",
    remoteId: "job-1",
    status: "running",
  }];
  vm.runInContext(`jobs.set(${JSON.stringify(key)}, makeJob(${JSON.stringify(key)}, 'https://site.example/', 'https://img.example/a.png'))`, context);
  await vm.runInContext("resumeStoredJobs()", context);
  const count = vm.runInContext("jobs.size", context);
  assert.equal(count, 1);
});

test("resume без ключа сопряжения даёт ошибку", async () => {
  const { context } = background();
  await vm.runInContext(`(async () => {
    const job = makeJob(cacheKey('https://site.example/', 'https://img.example/a.png'), 'https://site.example/', 'https://img.example/a.png');
    job.remoteId = 'stale';
    job.status = 'running';
    await resumeRemote(job);
    globalThis._resumeError = job.status;
    globalThis._resumeMessage = job.error;
  })()`, context);
  assert.equal(vm.runInContext("_resumeError", context), "error");
  assert.match(String(vm.runInContext("_resumeMessage", context)), /ключ/i);
});

test("Сохранить перевод качает файл с языком в имени", async () => {
  const { context, events } = background();
  vm.runInContext(`jobs.set(cacheKey('https://site.example/','https://img.example/large.png'), {status:'done', blob:{}, mime:'image/png', targetLang:'ru', imageUrl:'https://img.example/large.png', imageBase64:'QQ=='})`, context);
  vm.runInContext(`onContextMenuClick({menuItemId:'ilt-save-translation',srcUrl:'https://img.example/large.png',frameId:2},{id:0,windowId:7})`, context);
  await new Promise(resolve => setTimeout(resolve, 20));
  const save = events.find(event => event[0] === "inline" && event[2].type === "inline-save");
  assert.equal(save[3].frameId, 2);
  const download = events.find(event => event[0] === "download");
  assert.equal(download[1].filename, "large.ru.png");
  assert.equal(download[1].saveAs, true);
  assert.match(download[1].url, /^data:image\/png;base64,/);
});


function uploadContext(health = { max_body_bytes: 64 * 1024 * 1024 }) {
  const { context } = background();
  const calls = [];
  Object.assign(context, {
    Blob, FormData, Response,
    fetch: async (url, options) => {
      calls.push({ url, options });
      return Response.json(url.endsWith('/v1/health') ? health : { job_id: 'large-job' });
    },
  });
  return { context, calls };
}

const uploadCall = `postTranslate('http://127.0.0.1:8765', 'secret', uploadImage,
  {imageUrl:'https://img.example/original.png', targetLang:'ru', fresh:true})`;

test('Оригинал 29 865 297 байт проходит новый лимит и сохраняется в multipart', async () => {
  const { context, calls } = uploadContext();
  context.uploadImage = new Blob([new Uint8Array(29_865_297)], { type: 'image/png' });
  assert.equal(await vm.runInContext(uploadCall, context), 'large-job');
  assert.equal(calls.length, 2);
  const posted = calls[1].options.body;
  assert.ok(posted instanceof Blob);
  assert.match(posted.type, /^multipart\/form-data;\s*boundary=/);
  assert.ok(posted.size > context.uploadImage.size);
  const form = await new Response(posted).formData();
  assert.equal(form.get('file').size, context.uploadImage.size);
  assert.equal(form.get('file').type, 'image/png');
  assert.equal(form.get('target_lang'), 'ru');
  assert.equal(form.get('fresh'), '1');
  assert.deepEqual(await form.get('file').arrayBuffer(), await context.uploadImage.arrayBuffer());
});

test('Старый сервер и некорректный лимит: большой файл не передаётся', async () => {
  for (const health of [{}, {max_body_bytes:0}, {max_body_bytes:-1}, {max_body_bytes:'67108864'}, {max_body_bytes:1.5}, {max_body_bytes:Number.MAX_VALUE}]) {
    const { context, calls } = uploadContext(health);
    context.uploadImage = new Blob([new Uint8Array(21 * 1024 * 1024)]);
    await assert.rejects(vm.runInContext(uploadCall, context), error => error.code === 'E_UPLOAD_SIZE' && /20 МиБ/.test(error.message));
    assert.equal(calls.length, 1);
    const entry = vm.runInContext('logMemory.at(-1)', context);
    assert.equal(entry.data.code, 'E_UPLOAD_SIZE');
    assert.equal(JSON.stringify(entry).includes('secret'), false);
  }
});

test('Размер файла ниже лимита, но multipart выше: POST не начинается', async () => {
  const { context, calls } = uploadContext({max_body_bytes:1024});
  context.uploadImage = new Blob([new Uint8Array(1024)], {type:'image/png'});
  await assert.rejects(vm.runInContext(uploadCall, context), error => error.code === 'E_UPLOAD_SIZE');
  assert.equal(calls.length, 1);
  assert.ok(vm.runInContext('logMemory.at(-1).data.checkedBytes', context) > 1024);
});

test('Точный лимит multipart принимается, один лишний байт блокируется', async () => {
  const probe = uploadContext();
  probe.context.uploadImage = new Blob(['image'], {type:'image/png'});
  await vm.runInContext(uploadCall, probe.context);
  const bodySize = probe.calls[1].options.body.size;
  for (const [limit, allowed] of [[bodySize, true], [bodySize - 1, false]]) {
    const { context, calls } = uploadContext({max_body_bytes:limit});
    context.uploadImage = probe.context.uploadImage;
    if (allowed) assert.equal(await vm.runInContext(uploadCall, context), 'large-job');
    else await assert.rejects(vm.runInContext(uploadCall, context), error => error.code === 'E_UPLOAD_SIZE');
    assert.equal(calls.length, allowed ? 2 : 1);
  }
});

test('413 сохраняет причину, HTTP-статус и код без секрета', async () => {
  for (const response of [Response.json({error:'Картинка больше 40 000 000 пикселей'}, {status:413}), new Response('too large', {status:413}), Response.json({}, {status:413})]) {
    const { context } = uploadContext();
    context.fetch = async () => response;
    await assert.rejects(vm.runInContext(`fetchApi('http://127.0.0.1:8765/v1/translate', {method:'POST', headers:{Authorization:'Bearer secret'}})`, context), error => error.code === 'E_HTTP_413' && !/сервер не найден/.test(error.message));
    const entry = vm.runInContext('logMemory.at(-1)', context);
    assert.equal(entry.data.status, 413);
    assert.equal(entry.data.path, '/v1/translate');
    assert.equal(JSON.stringify(entry).includes('secret'), false);
  }
});

test('Сетевой TypeError отличается от локального TypeError', async () => {
  const { context } = uploadContext();
  context.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(vm.runInContext(`fetchApi('http://127.0.0.1:8765/v1/health')`, context), error => error.code === 'E_NETWORK');
  assert.equal(vm.runInContext(`toPipelineError(new TypeError('Ошибка сериализации'))`, context), 'Ошибка сериализации');
});

test('executeJob сохраняет код отказа загрузки в сводке задания', async () => {
  const { context } = uploadContext({max_body_bytes:1});
  context.chrome.storage.local.get = async () => ({serverUrl:'http://127.0.0.1:8765', token:'secret', targetLang:'ru'});
  context.uploadImage = new Blob(['large'], {type:'image/png'});
  await vm.runInContext(`(async () => {
    const job = makeJob('test', 'https://site.example/', 'https://img.example/a.png');
    job.suppliedBlob = uploadImage;
    await executeJob(job);
    globalThis.failedJob = job;
  })()`, context);
  assert.equal(context.failedJob.status, 'error');
  assert.equal(context.failedJob.errorCode, 'E_UPLOAD_SIZE');
  assert.match(context.failedJob.error, /лимит/);
});
