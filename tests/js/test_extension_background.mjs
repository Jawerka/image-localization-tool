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
  const context = vm.createContext({ chrome, queueMicrotask, setTimeout, clearTimeout, AbortController, URL });
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
  const { context, state } = background();
  const calls = [];
  Object.assign(context, {
    Blob, FormData, Response,
    fetch: async (url, options) => {
      calls.push({ url, options });
      return Response.json(url.endsWith('/v1/health') ? health : { job_id: 'large-job' });
    },
  });
  return { context, calls, state };
}

const uploadCall = `postTranslate('http://127.0.0.1:8765', 'secret', uploadImage,
  {imageUrl:'https://img.example/original.png', targetLang:'ru', fresh:true})`;

test('Оригинал 29 865 297 байт проходит новый лимит и сохраняется в multipart', async () => {
  const { context, calls } = uploadContext();
  context.uploadImage = new Blob([new Uint8Array(29_865_297)], { type: 'image/png' });
  assert.equal(await vm.runInContext(uploadCall, context), 'large-job');
  assert.equal(calls.length, 2);
  const posted = calls[1].options.body;
  assert.ok(posted instanceof FormData);
  assert.equal(calls[1].options.headers["X-Target-Lang"], "ru");
  assert.equal(calls[1].options.headers["Content-Type"], undefined);
  const form = posted instanceof FormData ? posted : await new Response(posted).formData();
  assert.ok(form.get("file").size > 0);
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
  const bodySize = (await new Response(probe.calls[1].options.body).blob()).size;
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


test('Запасное скачивание разрешает HTTP-кэш расширения', async () => {
  const { context } = uploadContext();
  let options;
  context.fetch = async (_url, supplied) => { options = supplied; return new Response('image', {headers:{'content-type':'image/webp'}}); };
  const blob = await vm.runInContext(`downloadImage('https://img.example/a.webp', 'https://site.example/')`, context);
  assert.equal(await blob.text(), 'image');
  assert.equal(options.cache, 'force-cache');
});

test('Ошибка загрузки сохраняет тип сбоя и origin без подписанного URL', async () => {
  const { context } = uploadContext();
  context.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(vm.runInContext(`downloadImage('https://img.example/a.webp?private=key', 'https://site.example/')`, context), error => error.code === 'E_DOWNLOAD');
  const entries = vm.runInContext('logMemory', context);
  assert.equal(entries[0].data.name, 'TypeError');
  assert.equal(entries[0].data.origin, 'https://img.example/');
  assert.equal(JSON.stringify(entries).includes('private'), false);
});

test('Запасное скачивание отвергает пустой либо непрозрачный ответ', async () => {
  for (const response of [new Response(''), {ok:true,type:'opaque',status:0}]) {
    const { context } = uploadContext();
    context.fetch = async () => response;
    await assert.rejects(vm.runInContext(`downloadImage('https://img.example/a.webp', 'https://site.example/')`, context), error => error.code === 'E_DOWNLOAD');
  }
});

test('Переданные байты страницы обходят повторное скачивание оригинала', async () => {
  const { context, calls } = uploadContext();
  context.chrome.storage.local.get = async () => ({serverUrl:'http://127.0.0.1:8765', token:'secret', targetLang:'ru'});
  await vm.runInContext(`(async () => {
    const job = makeJob('source-test', 'https://site.example/', 'https://unavailable.example/a.png');
    job.suppliedBlob = new Blob(['cached-original'], {type:'image/png'});
    pollJob = async () => {};
    fetchResult = async () => ({blob:new Blob(['translated'], {type:'image/png'}),mime:'image/png'});
    finishLocal = async job => {job.status='done';};
    deleteRemote = async () => {};
    await executeJob(job);
    globalThis.finishedSourceJob = job;
  })()`, context);
  assert.equal(context.finishedSourceJob.status, 'done');
  assert.equal(calls.some(call => call.url.includes('unavailable.example')), false);
  const form = await new Response(calls.find(call => call.options.method === 'POST').options.body).formData();
  assert.equal(await form.get('file').text(), 'cached-original');
});


test('Байты HTTP-оригинала со страницы сохраняют кэш готового перевода и fresh', async () => {
  for (const fresh of [false, true]) {
    const { context, calls } = uploadContext();
    context.chrome.storage.local.get = async () => ({serverUrl:'http://127.0.0.1:8765', token:'secret', targetLang:'ru'});
    context.freshTest = fresh;
    await vm.runInContext(`(async () => {
      const job = makeJob('result-cache-test', 'https://site.example/', 'https://img.example/a.png');
      job.suppliedBlob = new Blob(['original'], {type:'image/png'});
      job.fresh = freshTest;
      readResultCache = async () => new Blob(['existing-translation'], {type:'image/png'});
      pollJob = async () => {};
      fetchResult = async () => ({blob:new Blob(['fresh-translation'], {type:'image/png'}),mime:'image/png'});
      finishLocal = async job => {job.status='done';};
      deleteRemote = async () => {};
      await executeJob(job);
      globalThis.cachedSourceJob = job;
    })()`, context);
    assert.equal(await context.cachedSourceJob.blob.text(), fresh ? 'fresh-translation' : 'existing-translation');
    assert.equal(calls.length, fresh ? 2 : 0);
  }
});


test('Дедлайн охватывает заголовки, успешное и ошибочное тело', async () => {
  for (const phase of ['headers', 'body', 'error-body']) {
    const {context} = uploadContext();
    context.fetch = phase === 'headers' ? () => new Promise(() => {}) : async () => ({
      ok: phase === 'body', status: phase === 'body' ? 200 : 500,
      json: () => new Promise(() => {}),
    });
    await assert.rejects(vm.runInContext(`fetchApi('http://localhost/v1/health', {}, 'json', 15)`, context),
      e => e.code === 'E_API_TIMEOUT' && e.stage === phase);
  }
});

test('Истёкший срок задания не начинает GET или новый POST', async () => {
  const {context, calls} = uploadContext();
  await assert.rejects(vm.runInContext(`pollJob('http://localhost', 'secret', {remoteId:'old', deadlineAt:Date.now()-1})`, context), e => e.code === 'E_JOB_TIMEOUT');
  assert.equal(calls.length, 0);
});

test('Неопределённый POST не повторяется', async () => {
  const {context, calls} = uploadContext();
  context.fetch = async (url, options) => {
    calls.push({url, options});
    if (options?.method === 'POST') throw new TypeError('Failed to fetch');
    return Response.json({});
  };
  context.uploadImage = new Blob(['image'], {type:'image/png'});
  await assert.rejects(vm.runInContext(uploadCall, context), e => e.code === 'E_NETWORK');
  assert.equal(calls.filter(x => x.options?.method === 'POST').length, 1);
});


test('Referer fallback владеет правилом до конца тела', async () => {
  const {context} = uploadContext();
  let rule = null;
  const seen = [];
  context.chrome.declarativeNetRequest = {updateSessionRules: async change => {
    if (change.removeRuleIds) rule = null;
    if (change.addRules) rule = change.addRules[0];
  }};
  const attempts = new Map();
  context.fetch = async url => {
    const n = attempts.get(url) || 0;
    attempts.set(url, n + 1);
    if (!n) return {ok:false,status:403};
    await new Promise(resolve => setTimeout(resolve, 5));
    seen.push({url, filter:rule?.condition.urlFilter});
    return {ok:true,status:200,blob:async () => {
      await new Promise(resolve => setTimeout(resolve, 5));
      assert.equal(rule.condition.urlFilter, url);
      return new Blob(['image']);
    }};
  };
  await vm.runInContext(`Promise.all([
    downloadImage('https://a.example/a.png', 'https://page-a.example/'),
    downloadImage('https://b.example/b.png', 'https://page-b.example/')])`, context);
  assert.equal(seen.length, 2);
  for (const row of seen) assert.equal(row.filter, row.url);
  assert.equal(rule, null);
});

test('Срок задания сохраняется и не меняется при повторном polling', async () => {
  const {context, state} = uploadContext();
  context.fetch = async () => Response.json({status:'done'});
  await vm.runInContext(`(async()=>{
    const job = makeJob('deadline', 'https://site.example/', 'https://img.example/a.png');
    job.remoteId='remote'; job.status='running'; jobs.set(job.key, job);
    await pollJob('http://localhost', 'secret', job);
    globalThis.deadline = job.deadlineAt;
    await pollJob('http://localhost', 'secret', job);
    globalThis.sameDeadline = job.deadlineAt === deadline;
  })()`, context);
  assert.equal(context.sameDeadline, true);
  assert.equal(state.iltJobs[0].deadlineAt, context.deadline);
});


test('Дедлайн blob охватывает чтение результата', async () => {
  const {context} = uploadContext();
  context.fetch = async () => ({ok:true, blob:() => new Promise(() => {})});
  await assert.rejects(vm.runInContext(`fetchApi('http://localhost/result', {}, 'blob', 15)`, context),
    e => e.code === 'E_API_TIMEOUT' && e.stage === 'body');
});

test('Ошибка тела fallback освобождает DNR правило', async () => {
  const {context} = uploadContext();
  let rule = null, attempts = 0;
  context.chrome.declarativeNetRequest = {updateSessionRules: async change => {
    rule = change.addRules?.[0] || null;
  }};
  context.fetch = async () => ++attempts === 1 ? {ok:false,status:403} : {
    ok:true, blob:async () => {throw new Error('body failed');}
  };
  await assert.rejects(vm.runInContext(`downloadImage('https://a.example/a.png','https://site.example/')`, context));
  assert.equal(rule, null);
});


test('Обрыв JSON тела не превращается в успешный null', async () => {
  const {context} = uploadContext();
  context.fetch = async () => ({ok:true,json:async () => {throw new TypeError('connection reset');}});
  await assert.rejects(vm.runInContext(`fetchApi('http://localhost/job')`, context), e => e.code === 'E_NETWORK');
  assert.equal(vm.runInContext(`logMemory.some(x=>x.ev==='request-complete')`, context), false);
});

test('Истечение общего срока внутри тела отличимо от сетевого таймаута', async () => {
  const {context} = uploadContext();
  context.fetch = async () => ({ok:true,json:() => new Promise(() => {})});
  await assert.rejects(vm.runInContext(`pollJob('http://localhost', 'secret', {remoteId:'slow',deadlineAt:Date.now()+20})`, context),
    e => e.code === 'E_JOB_TIMEOUT');
});
