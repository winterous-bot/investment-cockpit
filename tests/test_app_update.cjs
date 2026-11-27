'use strict';
const assert=require('node:assert/strict'),{check,compare,freshURL}=require('../app-update.js');
const fs=require('node:fs'),vm=require('node:vm'),base='https://example.test/investment-cockpit/index.html?settings=1';
async function main(){
 assert.equal(compare('2.10.0','2.9.9'),1);assert.equal(compare('2.2.6','2.2.6'),0);assert.throws(()=>compare('x','2.2.6'));
 assert.throws(()=>freshURL(base,'https://other.test/',1));
 const seen=[],fetcher=async (url,opts)=>{seen.push({url,opts});return {ok:true,json:async()=>({version:'2.2.6'}),text:async()=>'<meta name="northstar-app-version" content="2.2.6">'}};
 const target=await check(base,'2.2.5',fetcher,123);
 assert.equal(target.version,'2.2.6');assert.match(target.url,/app_update=123/);assert.match(target.url,/settings=1/);assert.match(target.url,/expected_version=2.2.6/);
 assert.equal(seen.length,2);assert(seen.every(x=>x.opts.cache==='no-store'&&x.url.startsWith('https://example.test/investment-cockpit/')));
 assert.equal((await check(base,'2.2.6',fetcher,124)).version,'2.2.6');
 await assert.rejects(check(base,'2.2.7',fetcher,125),/旧版本/);
 await assert.rejects(check(base,'2.2.5',async()=>({ok:true,json:async()=>({version:'2.2.6'}),text:async()=>'<meta name="northstar-app-version" content="2.2.5">'})),/尚未同步/);
 await assert.rejects(check(base,'2.2.5',async()=>{throw Error('offline')}),/offline/);
 const code=fs.readFileSync('app-update.js','utf8'),sw=fs.readFileSync('sw.js','utf8');
 assert(!/localStorage|sessionStorage|indexedDB|\.unregister\(|\.delete\(/.test(code));
 assert.match(sw,/fetch\(e.request,\{cache:'no-store',signal:c.signal\}\)/);
 // Simulate worker navigation and install using mock cache and network.
 const release=JSON.parse(fs.readFileSync('release.json','utf8')).version,old='0.0.1',shell=v=>'northstar-shell-v'+v,html=v=>'<meta name="northstar-app-version" content="'+v+'">';
 const handlers={},cached=new Map(),cache={addAll:async reqs=>{for(const r of reqs){assert.equal(r.cache,'reload');cached.set(r.url,new Response(html(release)))}},match:async p=>cached.get(new URL(p,base).href)?.clone()};
 let skipped=0,claimed=0,deleted=[],requests=[],offline=false;
 const self={registration:{scope:'https://example.test/investment-cockpit/'},location:{origin:'https://example.test'},skipWaiting:async()=>{skipped++},clients:{claim:async()=>{claimed++}},addEventListener:(name,fn)=>handlers[name]=fn};
 const caches={open:async()=>cache,keys:async()=>[shell(old),'private-unrelated-cache',shell(release)],delete:async k=>deleted.push(k),match:cache.match};
 vm.runInNewContext(sw,{self,caches,URL,Request,Response,AbortController,setTimeout,clearTimeout,fetch:async(r,o)=>{requests.push(o);if(offline)throw Error('offline');return new Response('fresh')}});
 let task;handlers.install({waitUntil:p=>task=p});await task;assert.equal(skipped,1);
 handlers.activate({waitUntil:p=>task=p});await task;assert.deepEqual(deleted,[shell(old)]);assert.equal(claimed,1);
 const event={request:{method:'GET',mode:'navigate',url:base},respondWith:p=>task=p};handlers.fetch(event);assert.equal(await (await task).text(),'fresh');assert.equal(requests.at(-1).cache,'no-store');
 offline=true;handlers.fetch(event);assert.equal(await (await task).text(),html(release));
 // Refuse activation of a mixed-version shell.
 cache.addAll=async()=>{cached.set(new URL('./growth.html',base).href,new Response(html(old)))};
 handlers.install({waitUntil:p=>task=p});await assert.rejects(task,/not synchronized/);assert.equal(skipped,1);
 console.log('App update: fresh release and HTML check, same-version reload, stale/mismatch/offline rejection, network-first navigation, version-verified shell installation and private storage preservation passed.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
