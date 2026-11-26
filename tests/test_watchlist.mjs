import assert from 'node:assert/strict';
import {randomBytes,webcrypto} from 'node:crypto';
import {mkdtempSync,readFileSync,writeFileSync,mkdirSync,readdirSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import {seal,open,prepare,assemble,slot,priorManifest,codesValid} from '../company/watchlist_seal.mjs';
const require=createRequire(import.meta.url),ui=require('../watchlist.js'),{create,pathFor,TTL}=require('../snapshot-store.js');
const key=randomBytes(32),a='000001.SZ',b='600001.SH',day='20261125',day2='20261126',manifestDomain='northstar-watchlist-v11';
const k=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt','decrypt']);
const dir=mkdtempSync(join(tmpdir(),'watchlist-test-')),work=join(dir,'private'),target=join(dir,'public');mkdirSync(work);mkdirSync(target);
const write=(p,x)=>writeFileSync(p,JSON.stringify(x)),read=p=>JSON.parse(readFileSync(p,'utf8'));
const directory=[{code:a,name:'示例甲',industry:'制造'},{code:b,name:'示例乙',industry:'制造'},...Array.from({length:4500},(_,i)=>({code:String(300000+i).padStart(6,'0')+'.SZ',name:'样本',industry:'制造'}))];
write(join(work,'directory.json'),directory);
function results(codes,date,statuses){const entries=codes.map((code,i)=>{const status=statuses[i];if(status!=='ready')return {code,status,reason:'vendor_api_error'};const file='company-'+i+'.json';write(join(work,file),{code,asof:date,valuation:{share_verified:true},profile:{ttm:{revenue:100,deducted_profit:5,cfo:6,capex:1}}});return {code,status,file,asof:date,quote_date:date}});write(join(work,'results.json'),{asof:date,quote_date:date,entries})}
async function req(prior,codes){const date=day;return JSON.stringify(await ui.encrypt({version:'watchlist-request-v1.1',base:prior.revision,asof:date,codes},k,'northstar-watchlist-request-v11',date))}
try{
 // Search UX: successful persistence clears results and dismisses mobile keyboard.
 let field={value:'示例甲',blur(){this.blurred=true}},renders=0;
 assert.equal(await ui.completeSearchAdd(field,async()=>true,()=>renders++),true);
 assert.equal(field.value,'');assert.equal(field.blurred,true);assert.equal(renders,1);
 field={value:'示例乙',blur(){this.blurred=true}};
 assert.equal(await ui.completeSearchAdd(field,async()=>false,()=>renders++),false);
 assert.equal(field.value,'示例乙');assert.equal(field.blurred,undefined);assert.equal(renders,1);
 // Do not erase a new search typed while the prior save was in flight.
 assert.equal(await ui.completeSearchAdd(field,async()=>{field.value='下一只';return true},()=>renders++),true);
 assert.equal(field.value,'下一只');assert.equal(field.blurred,undefined);assert.equal(renders,1);
 assert.throws(()=>codesValid([a,a]));assert.throws(()=>codesValid(['../']));assert.throws(()=>codesValid(directory.slice(0,21).map(x=>x.code)));
 assert.equal(pathFor('company:'+slot(key,a)),'companies/'+slot(key,a)+'.enc.json');assert.equal(pathFor('company:../'),null);assert.equal(pathFor('constructor'),null);
 const e=priorManifest(key,target),boot=prepare(key,e,'bootstrap','');assert.deepEqual(boot.codes,[]);results([],day,[]);let m=assemble(key,e,boot,work,target);
 assert.equal(m.entries.length,0);assert.equal(readdirSync(join(target,'companies')).length,0);
 assert.throws(()=>prepare(key,m,'bootstrap',''));
 const cipher=await req(m,[a,b]),q=prepare(key,m,'sync',cipher);assert.deepEqual(q.codes,[a,b]);assert(!cipher.includes(a));assert.throws(()=>prepare(randomBytes(32),m,'sync',cipher));assert.throws(()=>prepare(key,m,'sync','{"codes":[]}'));
 results([a,b],day,['ready','ready']);m=assemble(key,m,q,work,target);assert.equal(m.entries.length,2);assert.throws(()=>prepare(key,m,'sync',cipher));
 const browser=await ui.decrypt(read(join(target,'watchlist.enc.json')),k,manifestDomain);assert(ui.validManifest(browser,read(join(target,'watchlist.enc.json'))));assert.deepEqual(browser,m);
 const id=slot(key,a),id2=slot(key,b),pa=join(target,'companies',id+'.enc.json'),pb=join(target,'companies',id2+'.enc.json');
 assert(existsSync(pa)&&existsSync(pb));assert(!readFileSync(pa,'utf8').includes(a));assert(!readdirSync(join(target,'companies')).some(f=>f.includes(a)));
 assert.equal((await ui.decrypt(read(pa),k,'northstar-company-v11:'+id)).company.code,a);
 await assert.rejects(ui.decrypt(read(pa),k,'northstar-company-v11:'+id2));await assert.rejects(ui.decrypt(read(pa),await webcrypto.subtle.importKey('raw',randomBytes(32),'AES-GCM',false,['decrypt']),'northstar-company-v11:'+id));
 // Failed single-company update leaves previous valid ciphertext untouched.
 const before=readFileSync(pa,'utf8'),refresh=prepare(key,m,'refresh','');assert.equal(refresh.revision,m.revision);results([a,b],day2,['failed','ready']);m=assemble(key,m,refresh,work,target);assert.equal(readFileSync(pa,'utf8'),before);assert.equal(m.entries[0].report_asof,day);assert.equal(m.entries[1].report_asof,day2);
 const draft={version:'watchlist-draft-v1.1',base:m.revision,codes:[a],labels:[]};assert(ui.validDraft(draft));assert.equal(ui.reconcile(draft,m).synced,false);
 const newReq=prepare(key,m,'sync',await req(m,[a]));results([a],day2,['failed']);m=assemble(key,m,newReq,work,target);assert.equal(m.entries.length,1);assert(!existsSync(pb));assert(existsSync(pa));assert(ui.reconcile(draft,m).synced);
 assert(ui.reconcile({...draft,codes:[b]},m).conflict);
 // A new company has its own cache slot; other reports are never requested.
 const memory=new Map(),calls=[];const st={get:async x=>memory.get(x)||null,put:async(x,v)=>{memory.set(x,v);return true},clear:async()=>memory.clear()};
 const rev='a'.repeat(40),packet=read(pa),opts={decode:q=>ui.decrypt(q,k,'northstar-company-v11:'+id),show(){},notify(){}};
 const fetcher=async u=>{calls.push(u);return {ok:true,json:async()=>u.includes('api.github.com')?[{sha:rev}]:packet}};
 const manager=()=>create({store:st,fetcher,now:()=>1000000});
 await manager().load('company:'+id,opts);assert.equal(calls.length,2);assert(calls.every(u=>!u.includes(id2)));await manager().load('company:'+id,opts);assert.equal(calls.length,2);
 console.log('Watchlist validation passed: empty default, encrypted browser request, authentication, replay prevention, deletion, stale preservation, independent local-first shard.');
 if(process.argv[2]){
  const w=process.argv[2],r=read(join(w,'results.json')),d=read(join(w,'directory.json'));
  assert.equal(r.entries.length,5);assert(r.entries.every(x=>x.status==='ready'),'All five sample reports must be ready');
  const out=join(dir,'real'),req={codes:r.entries.map(x=>x.code),revision:randomBytes(16).toString('hex')};mkdirSync(out);
  const p=assemble(key,priorManifest(key,out),req,w,out);assert.equal(p.entries.length,5);
  // Browser decrypts each report; run actual renderer on a minimal DOM.
  const view=readFileSync(new URL('../company-view.js',import.meta.url),'utf8');
  class El{constructor(){this.children=[];this.style={};this.textContent=''}append(...a){this.children.push(...a)}replaceChildren(...a){this.children=a}}
  const nodes=new Map(),get=x=>{if(!nodes.has(x))nodes.set(x,new El());return nodes.get(x)};
  const ctx={window:{},document:{createElement:()=>new El(),getElementById:get}};vm.runInNewContext(view,ctx);
  for(const e of p.entries){const x=await ui.decrypt(read(join(out,'companies',e.id+'.enc.json')),k,'northstar-company-v11:'+e.id);assert.equal(x.company.code,e.code);ctx.window.NorthstarCompanyView.render(x.company);assert.equal(get('content').children.length,6)}
  console.log(JSON.stringify({real_test_companies:5,authenticated_shards:5,rendered_profiles:5,directory_count:d.length}));
 }
}finally{rmSync(dir,{recursive:true,force:true})}
