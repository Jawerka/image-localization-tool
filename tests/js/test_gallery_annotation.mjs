// Проверка выделения рамок, масштаба, отмены и сохранения комментария.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const template=fs.readFileSync(new URL('../../scripts/templates/review_gallery.html',import.meta.url),'utf8');
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.events={};this.className='';this.value='';this.attributes={};this.classList={toggle:(name,on)=>{const names=new Set(this.className.split(' ').filter(Boolean));on?names.add(name):names.delete(name);this.className=[...names].join(' ')}}}
  appendChild(child){child.remove();child.parentElement=this;this.children.push(child);return child}
  remove(){if(this.parentElement){const list=this.parentElement.children;list.splice(list.indexOf(this),1);this.parentElement=null}}
  before(child){const parent=this.parentElement;child.remove();parent.children.splice(parent.children.indexOf(this),0,child);child.parentElement=parent}
  setAttribute(name,value){this.attributes[name]=value}
  addEventListener(name,callback){this.events[name]=callback}
  dispatch(name,event={}){this.events[name]?.({button:0,pointerId:1,preventDefault(){},...event})}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(selector==='[data-star]'?child.dataset.star!==undefined:selector.startsWith('.')?child.className.split(' ').includes(selector.slice(1)):child.tag===selector)?[child]:[],...child.querySelectorAll(selector)])}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null}
  setPointerCapture(id){this.capture=id}
  hasPointerCapture(id){return this.capture===id}
  releasePointerCapture(){this.capture=null}
}
const store={'ilt-review:annotation-run':JSON.stringify({'001':{rating:4,comment:'Мой прежний комментарий'}})};
function setup(){
  const controls=Object.fromEntries(['status','json','message','message-bottom','download','download-bottom','copy','copy-bottom','show','run-progress','progress-caption','eta'].map(id=>['#'+id,new Element('div')]));
  const article=new Element('article');article.dataset.id='001';
  const link=article.appendChild(new Element('a')),image=link.appendChild(new Element('img'));
  let bounds={left:100,top:50,width:1000,height:500};image.getBoundingClientRect=()=>bounds;
  const note=article.appendChild(new Element('textarea'));
  for(const star of [1,2,3,4,5,0]){const button=article.appendChild(new Element('button'));button.dataset.star=String(star)}
  const context={document:{head:new Element('head'),querySelector:s=>controls[s],querySelectorAll:()=>[article],createElement:tag=>new Element(tag)},localStorage:{getItem:key=>store[key],setItem:(key,value)=>store[key]=value},setInterval(){},setTimeout(){},Blob,URL,navigator:{}};
  const script=template.replace('/*RUN*/{}',JSON.stringify({run_id:'annotation-run'})).replace('/*MANIFEST*/[]',JSON.stringify([{id:'001',image:'test.png',status:'done'}])).replace('/*PROGRESS*/{}',JSON.stringify({state:'completed',total:1,done:1,error:0})).match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.createContext(context);vm.runInContext(script,context);
  return {article,note,controls,surface:article.querySelector('.mark-image'),button:article.querySelector('.mark-tools').querySelector('button'),resize:value=>bounds=value};
}
const ui=setup();ui.button.onclick();
ui.surface.dispatch('pointerdown',{clientX:350,clientY:150});
ui.surface.dispatch('pointermove',{clientX:850,clientY:450});
ui.surface.dispatch('pointerup',{clientX:850,clientY:450});
assert.equal(ui.note.value,'Мой прежний комментарий\n[Область (%): x1=25.0, y1=20.0, x2=75.0, y2=80.0]');
assert.equal(ui.surface.querySelectorAll('.mark-box').length,1);
assert.equal(JSON.parse(store['ilt-review:annotation-run'])['001'].rating,4);
assert.equal(JSON.parse(ui.controls['#json'].value).images[0].comment,ui.note.value);
ui.resize({left:100,top:50,width:500,height:250});
ui.surface.dispatch('pointerdown',{clientX:475,clientY:250});
ui.surface.dispatch('pointerup',{clientX:225,clientY:100});
assert.equal(ui.surface.querySelectorAll('.mark-box').length,2);
assert.equal(ui.note.value.split('\n')[1],ui.note.value.split('\n')[2]);
const saved=ui.note.value;
ui.surface.dispatch('pointerdown',{clientX:200,clientY:100});
ui.surface.dispatch('pointermove',{clientX:300,clientY:150});
ui.surface.dispatch('pointercancel');assert.equal(ui.note.value,saved);
ui.surface.dispatch('pointerdown',{clientX:200,clientY:100});
ui.surface.dispatch('pointerup',{clientX:201,clientY:101});assert.equal(ui.note.value,saved);
ui.surface.dispatch('pointerdown',{clientX:50,clientY:0});
ui.surface.dispatch('pointerup',{clientX:700,clientY:500});
assert(ui.note.value.endsWith('[Область (%): x1=0.0, y1=0.0, x2=100.0, y2=100.0]'));
ui.article.dispatch('keydown',{key:'Escape'});assert.equal(ui.button.attributes['aria-pressed'],'false');
const reloaded=setup();assert.equal(reloaded.surface.querySelectorAll('.mark-box').length,3);
reloaded.note.value='Исправленный комментарий';reloaded.note.oninput({target:reloaded.note});
assert.equal(reloaded.surface.querySelectorAll('.mark-box').length,0);
assert.equal(JSON.parse(store['ilt-review:annotation-run'])['001'].comment,'Исправленный комментарий');
console.log('PASS: XY percentages, reverse drag, resize, clamp, cancellation, click threshold, comments, ratings, JSON, reload and manual deletion');
