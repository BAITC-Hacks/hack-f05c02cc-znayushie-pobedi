import {test} from 'node:test';
import assert from 'node:assert/strict';
import {money,stockLabel,canPropose,safeUrl,esc,createApi,cartCount,ApiError,attachmentError,MAX_ATTACHMENT_BYTES,certificatesForDisplay,formatChatText} from '../src/core.js';

test('unknown fields are not replaced by zero stock or an assumed currency', () => {
  assert.equal(stockLabel({stock:null}), 'Наличие уточняется');
  assert.equal(money(null,null), 'Цена уточняется');
  assert.match(money(65920,null), /валюта не указана/);
  assert.doesNotMatch(money(65920,null), /₸/);
  assert.match(stockLabel({stock:23,unit:null,requires_live_check:true}), /В снимке: 23/);
  assert.doesNotMatch(stockLabel({stock:23,unit:null,requires_live_check:true}), /шт/);
});
test('snapshot quantity alone cannot enable a cart proposal', () => {
  assert.equal(canPropose({stock:23,can_add_to_cart:false,requires_live_check:true}),false);
  assert.equal(canPropose({stock:23,can_add_to_cart:true,requires_live_check:true}),false);
  assert.equal(canPropose({stock:0,can_add_to_cart:true,requires_live_check:false}),false);
  assert.equal(canPropose({stock:14,can_add_to_cart:true,requires_live_check:false}),true);
});
test('remote text and URLs cannot supply script markup', () => {
  assert.equal(safeUrl('javascript:alert(1)'), '');
  assert.equal(safeUrl('data:text/html,<script>'), '');
  assert.equal(safeUrl('https://ekt.kz/catalog/'), 'https://ekt.kz/catalog/');
  assert.equal(safeUrl('/assets/breaker.jpg'), '/assets/breaker.jpg');
  assert.equal(esc('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
});
test('preparation and confirmation use different server requests, no local cart', async () => {
  const calls=[];
  const api=createApi(async (path,options)=>{calls.push({path,...options});return {status:200,ok:true,json:async()=>({proposal_id:'p1',quantity:2})};});
  await api.propose('s1','demo-breaker-16a',2);
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/sessions/s1/cart/proposals');
  assert.deepEqual(JSON.parse(calls[0].body),{product_id:'demo-breaker-16a',quantity:2});
  for(const confirmation of [false,undefined,'true',1]) assert.throws(()=>api.confirm('s1','p1',confirmation), /явное подтверждение/);
  assert.equal(calls.length,1);
  await api.confirm('s1','p1',true);
  assert.equal(calls[1].path,'/api/sessions/s1/cart/proposals/p1/confirm');
  assert.deepEqual(JSON.parse(calls[1].body),{confirm:true});
});
test('chatting yes does not call cart confirmation', async () => {
  const calls=[];
  const api=createApi(async(path,options)=>{calls.push({path,...options});return {status:200,ok:true,json:async()=>({answer:'test'})};});
  await api.chat('s1','да, добавь');
  assert.deepEqual(calls.map(c=>c.path),['/api/chat']);
});
test('invalid quantities never send a request', () => {
  const api=createApi(()=>{throw new Error('unexpected request')});
  for(const quantity of [0,-1,1.5,NaN,Infinity,1001,'2']) assert.throws(()=>api.propose('s1','p1',quantity),/Количество/);
});
test('server conflicts and cancelled proposals are handled without inventing success', async () => {
  const api=createApi(async()=>({status:409,ok:false,json:async()=>({detail:{code:'live_stock_check_required',message:'Нужна проверка'}})}));
  await assert.rejects(api.propose('s1','515291',1), error=>error instanceof ApiError && error.status===409 && error.message==='Нужна проверка');
  const cancel=createApi(async()=>({status:204,ok:true}));
  assert.equal(await cancel.cancel('s1','p1'),null);
});
test('cart badge counts the server response', () => {
  assert.equal(cartCount({items:[{quantity:2},{quantity:3}]}),5);
  assert.equal(cartCount(null),0);
});
test('attachment uses FormData with a browser-selected boundary and never calls cart routes', async () => {
  const calls=[];
  const api=createApi(async(path,options)=>{calls.push({path,...options});return {status:200,ok:true,json:async()=>({answer:'Файл разобран',pending_action:null,products:[]})};});
  const file = new File(['C16 2 шт'], 'заявка.pdf', {type:'application/pdf'});
  await api.attachment('session/id',file,'  Найди эти позиции  ');
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/sessions/session%2Fid/attachments');
  assert.equal(calls[0].method,'POST');
  assert.deepEqual(calls[0].headers,{});
  assert.ok(calls[0].body instanceof FormData);
  assert.equal(calls[0].body.get('file').name,'заявка.pdf');
  assert.equal(calls[0].body.get('message'),'Найди эти позиции');
  assert.equal(calls[0].body.get('confirm'),null);
});
test('attachment network failure does not consume or change the file needed for retry', async () => {
  const calls=[];
  const api=createApi(async(path,options)=>{
    calls.push({path,...options});
    if (calls.length === 1) throw new TypeError('Failed to fetch');
    return {status:200,ok:true,json:async()=>({answer:'ok'})};
  });
  const file = new File(['product 515288'], 'заявка.DOCX');
  await assert.rejects(api.attachment('s1',file,'Ищу товар'),/Failed to fetch/);
  await api.attachment('s1',file,'Ищу товар');
  assert.equal(await calls[0].body.get('file').text(),await calls[1].body.get('file').text());
  assert.equal(calls[1].body.get('message'),'Ищу товар');
  assert.equal(calls[0].path,calls[1].path);
});
test('unsupported, empty or oversized attachments stop before any request', () => {
  const api=createApi(()=>{throw new Error('unexpected request')});
  assert.match(attachmentError({name:'old.doc',size:5}),/DOCX или PDF/);
  assert.match(attachmentError({name:'script.html',size:5}),/Поддерживаются/);
  assert.match(attachmentError({name:'photo.jpg',size:0}),/пустой/);
  assert.match(attachmentError({name:'book.xlsx',size:MAX_ATTACHMENT_BYTES+1}),/10 МБ/);
  assert.equal(attachmentError({name:'PHOTO.PNG',size:MAX_ATTACHMENT_BYTES}),'');
  assert.throws(()=>api.attachment('s1',{name:'script.exe',size:10}),/Поддерживаются/);
  assert.throws(()=>api.attachment('s1',new File(['x'],'list.xls'),'x'.repeat(2001)),/2000 символов/);
});
test('certificate links reject executable URLs and keep the explicit demo flag', () => {
  const records = certificatesForDisplay({certificates:[
    {title:'Паспорт',url:'https://ekt.kz/passport.pdf'},
    {title:'Пример',url:'/documents/demo-certificate.html',is_demo:true},
    {title:'Не ссылка',url:'javascript:alert(1)'},
    {title:'Данные',url:'data:text/html,example'},
    null,
  ]});
  assert.deepEqual(records,[
    {title:'Паспорт',url:'https://ekt.kz/passport.pdf',isDemo:false},
    {title:'Пример',url:'/documents/demo-certificate.html',isDemo:true},
  ]);
  assert.deepEqual(certificatesForDisplay({certificates:'untrusted text'}),[]);
});
test('session history is read from the same server session without creating a proposal', async () => {
  const calls=[];
  const saved={messages:[{role:'user',text:'C16',products:[]},{role:'bot',text:'Товар найден',products:[{id:'demo-breaker-16a'}]}]};
  const api=createApi(async(path,options)=>{calls.push({path,...options});return {status:200,ok:true,json:async()=>saved};});
  assert.deepEqual(await api.history('session/id'),saved);
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/sessions/session%2Fid/messages');
  assert.equal(calls[0].method,'GET');
  assert.equal(calls[0].body,undefined);
});
test('chat renders certificate and terms links without allowing other relative routes or markup', () => {
  const text = formatChatText('**Документы**: [Сертификат](/documents/demo-certificate.html) [Условия](/api/purchase-terms?demo=true&q=delivery) [EKT](https://ekt.kz/catalog/)');
  assert.match(text,/<strong>Документы<\/strong>/);
  assert.match(text,/href="\/documents\/demo-certificate.html"/);
  assert.match(text,/href="\/api\/purchase-terms\?demo=true&amp;q=delivery"/);
  assert.match(text,/href="https:\/\/ekt.kz\/catalog\/"/);
  for (const target of ['javascript:alert', 'data:text/html,test', '//example.com', '/\\example.com', '/api/sessions', '/documents/../api/sessions']) {
    assert.doesNotMatch(formatChatText(`[Текст](${target})`), /<a /);
  }
  const untrusted = formatChatText('[<img src=x onerror=alert>](/documents/demo.html) <script>alert(1)</script>');
  assert.doesNotMatch(untrusted, /<img|<script/);
  assert.match(untrusted,/&lt;img/);
  assert.match(untrusted,/rel="noopener noreferrer"/);
});
