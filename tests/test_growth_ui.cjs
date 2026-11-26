'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),{webcrypto,randomBytes}=require('node:crypto'),{gzipSync}=require('node:zlib');
const loader=fs.readFileSync('growth-loader.js','utf8'),view=fs.readFileSync('growth-view.js','utf8');
function harness(snapshot,hex){
 const elements=new Map();
 class El{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.className='';this.hidden=false;this.checked=false;this.value='';this.textContent='';this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);for(const n of nodes)if(n.id)elements.set(n.id,n)}
  replaceChildren(...nodes){this.children=[];this.append(...nodes)}
  setAttribute(){}
  querySelector(){return null}
  get valueAsNumber(){return this.value===''?NaN:Number(this.value)}
 }
 const get=id=>{if(!elements.has(id))elements.set(id,new El());return elements.get(id)};
 const key=hex,urls=[],window={};
 const ctx={document:{getElementById:get,createElement:t=>new El(t)},window,indexedDB:{open(){throw Error('blocked')}},localStorage:{getItem(k){assert.equal(k,'northstar-radar-fixed-key-v1');return key}},crypto:webcrypto,Blob,DecompressionStream,TextEncoder,TextDecoder,atob,Uint8Array,AbortController,setTimeout,clearTimeout,Intl,location:{protocol:'https:'},navigator:{},fetch:async u=>{urls.push(u);return {ok:true,json:async()=>u.includes('api.github.com')?[{sha:'a'.repeat(40)}]:snapshot}}};
 vm.runInNewContext(fs.readFileSync('snapshot-store.js','utf8'),ctx);vm.runInNewContext(view,ctx);vm.runInNewContext(loader,ctx);return {get,urls,window};
}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function ready(h){for(let i=0;i<200&&h.get('growthReload').disabled;i++)await wait(30)}
async function run(){
 const arg=process.argv[2],hex=arg?process.env.RADAR_KEY:randomBytes(32).toString('hex');let cipher,expected;
 if(arg){cipher=JSON.parse(fs.readFileSync(arg));expected=27;}
 else{
  const data={report:{version:'growth-scanner-v1.4.2',asof:'20261125',quote_date:'20261125',model_frozen:true,data_coverage_pass:true,complete_metrics:1,presets:JSON.parse(fs.readFileSync('growth/presets.json')),preset_statistics:{scenarios:[{id:'growth',quality_count:1},{id:'balanced',quality_count:1},{id:'steady',quality_count:1}]},periods:{latest:'20260930'},listed_shsz:1,industrial_commercial:1,quality_pass:1,quality_and_valuation_pass:1},rows:[{code:'000001.SZ',name:'测试公司',industry:'测试',revenue_cagr:.5,deducted_yoy:.6,roic:.25,cash_conversion:1.2,debt_ratio:.3,pe:20,market_cap:100,valuation:{close:10,quote_date:'20261125'},reverse_dcf:{status:'unavailable',reason:'missing_statement',category:'data'}}]};
  const key=await webcrypto.subtle.importKey('raw',Buffer.from(hex,'hex'),'AES-GCM',false,['encrypt']),iv=randomBytes(12);const encrypted=await webcrypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-growth-prod-v2:20261125'),tagLength:128},key,gzipSync(Buffer.from(JSON.stringify(data))));cipher={version:2,codec:'gzip',asof:'20261125',iv:iv.toString('base64'),ciphertext:Buffer.from(encrypted).toString('base64')};expected=1;
 }
 const html=fs.readFileSync('growth.html','utf8'),fold=html.match(/<details\b([^>]*\bid="filterSettings"[^>]*)>([\s\S]*?)<\/details>/);
 assert.ok(fold,'Native filter disclosure is present');assert.ok(!/\bopen\b/.test(fold[1]),'Filter disclosure starts collapsed');
 for(const id of ['filters','value','reset'])assert.ok(fold[2].includes('id="'+id+'"'),id+' must be inside disclosure');
 for(const id of ['presets','sceneNote','count','query','sort','rows'])assert.ok(!fold[2].includes('id="'+id+'"'),id+' must stay outside disclosure');
 const toolbar=html.match(/<div class="growth-toolbar">([\s\S]*?)<\/select><\/div>/);
 assert.ok(toolbar,'Compact results toolbar exists');
 assert.match(toolbar[1],/<input id="query" type="search" placeholder="搜索公司或行业" aria-label="搜索公司或行业"/);
 assert.match(toolbar[1],/<select id="sort" aria-label="排序">/);
 assert.deepEqual([...toolbar[1].matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]),['roic','revenue_cagr','deducted_yoy','cash_conversion','pe']);
 const css=fs.readFileSync('growth-ui.css','utf8');
 assert.match(css,/\.growth-toolbar\{display:grid;grid-template-columns:minmax\(0,1\.08fr\) minmax\(0,1fr\);align-items:center/);
 assert.match(css,/#query,#growthMain \.growth-toolbar #sort\{[^}]*height:44px/);
 const h=harness(cipher,hex);await ready(h);assert.match(h.get('growthStatus').textContent,/行情日期 20261125/);assert.equal(h.get('growthMain').hidden,false);assert.equal(h.get('presets').children.length,3);assert.match(h.get('count').textContent,new RegExp('符合条件 '+(arg?18:1)+' 家'));
 const counts=arg?[7,18,17]:[1,1,1];for(let i=0;i<3;i++){h.get('presets').children[i].onclick();assert.match(h.get('count').textContent,new RegExp('符合条件 '+counts[i]+' 家'))}
 const presetRoic=h.get('roic').value;h.get('roic').value=999;h.get('roic').oninput();assert.match(h.get('sceneNote').textContent,/已手动调整参数/);
 h.get('reset').onclick();assert.equal(h.get('roic').value,presetRoic);assert.match(h.get('sceneNote').textContent,/使用预设参数/);
 assert.equal(h.get('rows').children.length,counts[2]);assert.ok(h.urls.some(u=>u.includes('a'.repeat(40))));
 h.get('query').value='不可能匹配的测试关键词';h.get('query').oninput();assert.equal(h.get('rows').children.length,0);
 h.get('query').value='';h.get('query').oninput();assert.equal(h.get('rows').children.length,counts[2]);
 for(const sort of ['roic','revenue_cagr','deducted_yoy','cash_conversion','pe']){h.get('sort').value=sort;h.get('sort').onchange();assert.equal(h.get('rows').children.length,counts[2]);}
 const bad=harness(cipher,randomBytes(32).toString('hex'));await ready(bad);assert.match(bad.get('growthStatus').textContent,/未通过认证/);
 console.log('Growth UI: shared fixed-key fallback, authenticated gzip snapshot, all three scenario buttons, actual card rendering and wrong-key rejection passed.');
}
run().catch(e=>{console.error(e);process.exitCode=1});
