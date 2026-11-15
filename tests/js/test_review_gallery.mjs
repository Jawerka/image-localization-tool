// Проверка ручной приёмки и обоих наборов кнопок без просмотра изображений.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const __dirname=path.dirname(fileURLToPath(import.meta.url));
const template=fs.readFileSync(path.join(__dirname,'../../scripts/templates/review_gallery.html'),'utf8');
const rows=[{id:'001',image:'a.png',status:'done'},{id:'002',image:'nested/a.png',status:'done'}];
const script=template.replace('/*RUN*/{}',JSON.stringify({run_id:'existing-run'})).replace('/*MANIFEST*/[]',JSON.stringify(rows)).match(/<script>([\s\S]*?)<\/script>/)[1];
assert(!/position\s*:\s*(sticky|fixed)/.test(template));
for(const id of ['download','download-bottom','copy','copy-bottom'])assert(template.includes(`id="${id}"`));
const store={'ilt-review:existing-run':JSON.stringify({'001':{rating:3,comment:'Прежняя оценка'}})};
function setup(options={}){
  const controls={};
  for(const id of ['status','json','message','message-bottom','download','download-bottom','copy','copy-bottom','show','run-progress','progress-caption','eta'])controls['#'+id]={value:'',hidden:true,select(){this.selected=true}};
  const articles=rows.map(row=>{
    const stars=[1,2,3,4,5,0].map(n=>({dataset:{star:String(n)},classList:{toggle(){}}}));
    const note={value:''};const pending=options.pending&&row.id==='001'?{replaceWith(link){this.link=link}}:null;return {dataset:{id:row.id},querySelectorAll(){return stars},querySelector(s){return s==='.pending'?pending:note},stars,note,pending,remove(){}};
  });
  let downloaded,clipboard,lastBlob;
  const context={document:{head:{appendChild(){}},querySelector:s=>controls[s],querySelectorAll:()=>articles,createElement:()=>({appendChild(child){this.child=child},click(){downloaded=this.download}})},localStorage:{getItem:k=>store[k]||null,setItem:(k,v)=>{if(options.noStorage)throw Error('denied');store[k]=v}},navigator:{clipboard:{writeText:async value=>{if(options.noClipboard)throw Error('denied');clipboard=value}}},Blob,URL:{createObjectURL:blob=>{lastBlob=blob;return 'blob:test'},revokeObjectURL(){}},setTimeout:()=>{},setInterval:()=>{}};
  const source=options.pending?script.replace('"status":"done"','"status":"pending"'):script;
  vm.createContext(context);vm.runInContext(source,context);
  return {controls,articles,progress:context.iltReviewProgress,get downloaded(){return downloaded},get clipboard(){return clipboard},get blob(){return lastBlob}};
}
await (async()=>{
  const ui=setup();assert.equal(ui.articles[0].note.value,'Прежняя оценка');
  assert.equal(JSON.parse(ui.controls['#json'].value).images[0].rating,3);
  ui.articles[0].stars[3].onclick();ui.articles[0].note.oninput({target:{value:'Комментарий: "<>&"'}});
  const expected=JSON.parse(ui.controls['#json'].value);
  assert.equal(expected.images[0].rating,4);assert.equal(expected.images[0].comment,'Комментарий: "<>&"');assert.equal(expected.images[1].rating,null);
  assert.equal(setup().articles[0].note.value,'Комментарий: "<>&"');
  for(const id of ['download','download-bottom']){
    ui.controls['#'+id].onclick();assert.equal(ui.downloaded,'existing-run-ratings.json');
    assert.deepEqual(JSON.parse(await ui.blob.text()).images,expected.images);
  }
  for(const id of ['copy','copy-bottom']){
    await ui.controls['#'+id].onclick();assert.deepEqual(JSON.parse(ui.clipboard).images,expected.images);
    assert.equal(ui.controls['#message-bottom'].textContent,'JSON скопирован');
  }
  ui.articles[0].stars[5].onclick();assert.equal(JSON.parse(ui.controls['#json'].value).images[0].rating,null);
  assert.equal(JSON.parse(ui.controls['#json'].value).images[0].comment,'Комментарий: "<>&"');
  const live=setup({pending:true});live.articles[0].note.oninput({target:{value:'Пишу во время обработки'}});
  live.progress({run_id:'existing-run',state:'running',total:2,done:2,error:0,pages:[{id:'001',status:'done',result_sha256:'new-result'}]});
  assert.equal(live.articles[0].pending.link.child.src,'001/result.png');
  assert.equal(live.articles[0].note.value,'Комментарий: "<>&"');
  assert.equal(JSON.parse(live.controls['#json'].value).images[0].comment,'Пишу во время обработки');
  assert.equal(JSON.parse(live.controls['#json'].value).images[0].result_sha256,'new-result');
  const fallback=setup({noStorage:true,noClipboard:true});fallback.articles[0].stars[4].onclick();
  assert.equal(JSON.parse(fallback.controls['#json'].value).images[0].rating,5);
  await fallback.controls['#copy-bottom'].onclick();assert.equal(fallback.controls['#json'].hidden,false);
  fallback.controls['#download-bottom'].onclick();assert.equal(JSON.parse(await fallback.blob.text()).images[0].rating,5);
  ui.progress({run_id:'existing-run',state:'running',total:4,done:1,error:1,remaining_seconds:600,generated_at:new Date().toISOString(),current_image:'next.png',pages:[]});
  assert.equal(ui.controls['#run-progress'].max,4);assert.equal(ui.controls['#run-progress'].value,2);
  assert.match(ui.controls['#progress-caption'].textContent,/50%/);
  assert.match(ui.controls['#eta'].textContent,/Примерно осталось 10 мин/);
  assert.match(ui.controls['#eta'].textContent,/next.png/);
  ui.progress({run_id:'different-run',state:'completed',total:4,done:4,error:0,pages:[]});
  assert.equal(ui.controls['#run-progress'].value,2);
  ui.progress({run_id:'existing-run',state:'running',total:4,done:0,error:0,remaining_seconds:null,pages:[]});
  assert.match(ui.controls['#eta'].textContent,/после первой/);
  ui.progress({run_id:'existing-run',state:'completed_with_errors',total:4,done:3,error:1,pages:[]});
  assert.equal(ui.controls['#run-progress'].value,4);assert.match(ui.controls['#eta'].textContent,/не выполняется/);
  assert.equal(JSON.parse(ui.controls['#json'].value).images[0].comment,'Комментарий: "<>&"');
  console.log('PASS: existing ratings, both download/copy controls, comments, reset, reload, storage/clipboard fallback; no sticky header');
})().catch(error=>{console.error(error);process.exitCode=1});
