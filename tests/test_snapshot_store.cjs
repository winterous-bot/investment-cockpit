'use strict';
const assert=require('node:assert/strict'),{create,TTL}=require('../snapshot-store.js');
const A='a'.repeat(40),B='b'.repeat(40),C='c'.repeat(40);
const packet=(asof,ciphertext)=>({version:1,asof,iv:'valid-iv',ciphertext});
const q1=packet('20261125','first'),q2=packet('20261126','second'),q3=packet('20261126','corrected');
function disk(){
 const data=new Map();
 return {data,get:async k=>data.get(k)||null,put:async(k,v)=>{const o=data.get(k);if(o&&(o.snapshot.asof>v.snapshot.asof||(o.snapshot.asof===v.snapshot.asof&&o.requestedAt>v.requestedAt)))return false;data.set(k,structuredClone(v));return true},clear:async()=>data.clear()};
}
async function main(){
 const store=disk();let now=100000000,rev=A,q=q1,offline=false,corrupt=false,metadataFail=false,calls=[],shown=[],notices=[];
 const fetcher=async url=>{calls.push(url);if(offline||metadataFail&&url.includes('api.github.com'))throw Error('offline');return {ok:true,json:async()=>url.includes('api.github.com')?[{sha:rev}]:corrupt?{...q,ciphertext:'bad'}:q}};
 const manager=()=>create({store,fetcher,now:()=>now});
 const opts={decode:async p=>{if(p.ciphertext==='bad')throw new DOMException('bad','OperationError');return {secret:'decrypted-only-in-memory',asof:p.asof}},show:(d,p,source)=>shown.push({d,p,source}),notify:s=>notices.push(s)};
 const run=async(m,id='radar',force=false)=>{calls=[];shown=[];notices=[];await m.load(id,{...opts,force});return {calls:[...calls],shown:[...shown],notices:[...notices]}};
 let m=manager(),r=await run(m);assert.equal(r.calls.length,2);assert.equal(r.shown[0].source,'network');assert.equal(store.data.get('radar').rev,A);assert(!JSON.stringify([...store.data]).includes('decrypted-only-in-memory'));
 // Reload from an entirely fresh page instance; no network traffic in TTL.
 m=manager();r=await run(m);assert.equal(r.calls.length,0);assert.equal(r.shown[0].source,'local');
 now+=TTL+1;r=await run(manager());assert.equal(r.calls.length,1);assert.equal(r.shown[0].source,'local');
 // Manual refresh checks immediately; unchanged data still no large download.
 r=await run(manager(),'radar',true);assert.equal(r.calls.length,1);
 // Another module is independent.
 r=await run(manager(),'growth');assert.equal(r.calls.length,2);assert.equal(store.data.size,2);
 // New trade date and same-date correction each downloaded once and persisted.
 now+=TTL+1;rev=B;q=q2;r=await run(manager());assert.equal(r.calls.length,2);assert.equal(r.shown[0].p.asof,q1.asof);assert.equal(r.shown[1].p.asof,q2.asof);
 now+=TTL+1;rev=C;q=q3;r=await run(manager());assert.equal(r.calls.length,2);assert.equal(store.data.get('radar').snapshot.ciphertext,'corrected');
 // Offline metadata error: no large download, local render, retry throttle across fresh reload.
 now+=TTL+1;offline=true;r=await run(manager());assert.equal(r.calls.length,1);assert.equal(r.shown[0].source,'local');assert.match(r.notices.at(-1),/版本检查失败/);
 r=await run(manager());assert.equal(r.calls.length,0);
 offline=false;rev=A;q=q1;now+=TTL+1;r=await run(manager());assert.equal(store.data.get('radar').snapshot.ciphertext,'corrected');assert.match(r.notices.at(-1),/保留本地数据/);
 // Auth failure never overwrites local. Wrong key cannot show stored data.
 rev=B;q=q2;corrupt=true;now+=TTL+1;r=await run(manager());assert.equal(store.data.get('radar').snapshot.ciphertext,'corrected');assert.match(r.notices.at(-1),/更新失败/);
 let visible=0;await assert.rejects(manager().load('radar',{...opts,decode:async()=>{throw new DOMException('bad','OperationError')},show:()=>visible++}),/未通过认证/);assert.equal(visible,0);
 // Clear and force reauthentication.
 await manager().clear();assert.equal(store.data.size,0);
 // No persistent storage: works in memory, no false claim of persistence.
 corrupt=false;q=q1;const denied={get:async()=>{throw Error('denied')},put:async()=>{throw Error('denied')},clear:async()=>{throw Error('denied')}};
 const d=create({store:denied,fetcher,now:()=>now});r=await run(d);assert.match(r.notices.at(-1),/本机存储不可用/);r=await run(d);assert.equal(r.calls.length,0);
 console.log('Local-first tests passed: fresh reload zero requests, unchanged revision metadata-only, per-module isolation, new/same-day update, offline, rollback, wrong key, clear, storage denied.');
}
async function fallback(){
 const store=disk();let now=200000000,apiStatus=200,apiRev=A,pages=q2,raw=q2,calls=[],shown=[],notices=[];
 const q4=packet('20261127','friday-close'),q5=packet('20261130','monday-close');
 const fetcher=async url=>{calls.push(url);if(url.includes('api.github.com')){if(apiStatus===0)throw Error('offline metadata');return {ok:apiStatus===200,status:apiStatus,json:async()=>[{sha:apiRev}]}}
   const q=url.startsWith('./')?pages:raw;return {ok:true,json:async()=>q}};
 const manager=()=>create({store,fetcher,now:()=>now});
 const run=async(id='growth',force=false)=>{calls=[];shown=[];notices=[];await manager().load(id,{force,decode:async p=>{if(p.ciphertext==='bad')throw new DOMException('bad','OperationError');return p.asof},show:(d,p,source)=>shown.push({p,source}),notify:s=>notices.push(s)});return {calls:[...calls],shown:[...shown],notices:[...notices]}};
 await run();assert.equal(store.data.get('growth').snapshot.asof,'20261126');
 // Exact production failure: local date 26, commit API 403, Pages stale, Raw date 27.
 apiStatus=403;raw=q4;now+=1000;let r=await run('growth',true);
 assert.equal(r.calls.length,3);assert.match(r.calls[2],/raw.githubusercontent.com/);assert.equal(r.shown.at(-1).p.asof,'20261127');assert.equal(store.data.get('growth').rev,null);
 // Automatic retry remains throttled; direct download is not repeated on every reopen.
 r=await run();assert.equal(r.calls.length,0);
 // Rate-limited normal refresh can move to the next trading day.
 apiStatus=429;pages=q5;raw=q5;now+=TTL+1;r=await run();assert.equal(r.calls.length,2);assert.equal(r.shown.at(-1).p.asof,'20261130');
 // A stale mirror or a same-day unversioned different ciphertext cannot roll back.
 pages=q4;raw=packet('20261130','unverified-same-day');now+=1000;r=await run('growth',true);assert.equal(store.data.get('growth').snapshot.ciphertext,'monday-close');assert.match(r.notices.at(-1),/保留本地数据/);
 // Corrupt snapshots cannot overwrite a local authenticated snapshot.
 pages=raw=packet('20261201','bad');now+=1000;r=await run('growth',true);assert.equal(store.data.get('growth').snapshot.asof,'20261130');assert.match(r.notices.at(-1),/更新失败/);
 // Generic network failure: automatic mode keeps bandwidth guard; manual refresh tries mirrors.
 apiStatus=0;pages=raw=packet('20261201','tuesday-close');now+=TTL+1;r=await run();assert.equal(r.calls.length,1);
 r=await run('growth',true);assert.equal(r.shown.at(-1).p.asof,'20261201');
 // Once immutable version service recovers, same-date corrections work as before.
 apiStatus=200;apiRev=B;raw=packet('20261201','tuesday-corrected');now+=1000;r=await run('growth',true);assert.equal(store.data.get('growth').snapshot.ciphertext,'tuesday-corrected');assert.equal(store.data.get('growth').rev,B);
 console.log('Snapshot fallback: HTTP 403/429, stale Pages and newer Raw, manual metadata outage, retry throttling, same-day rollback guard, corrupt response and immutable recovery passed.');
}
main().then(fallback).catch(e=>{console.error(e);process.exitCode=1});
