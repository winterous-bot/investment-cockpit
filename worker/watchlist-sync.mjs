/* Owner-only dispatch gateway: does not receive a raw radar key or plaintext codes. */
const ORIGIN='https://winterous-bot.github.io', REPO='winterous-bot/investment-cockpit', DOMAIN='northstar-watchlist-sync-auth-v12';
const enc=new TextEncoder(), MAX=12000, ID=/^[0-9a-f]{32}$/, HEX=/^[0-9a-f]{64}$/i, DAY=/^\d{8}$/;
const headers={'content-type':'application/json; charset=utf-8','access-control-allow-origin':ORIGIN,'vary':'Origin','cache-control':'no-store','x-content-type-options':'nosniff'};
const json=(d,status=200)=>new Response(JSON.stringify(d),{status,headers});
const fail=(error,status)=>json({error},status);
const fromHex=s=>Uint8Array.from(s.match(/../g),x=>parseInt(x,16));
const toHex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
export function envelope(q){
 return q&&Object.keys(q).sort().join(',')==='asof,ciphertext,codec,iv,version'&&q.version===1&&q.codec==='json'&&typeof q.asof==='string'&&DAY.test(q.asof)&&typeof q.iv==='string'&&/^[A-Za-z0-9+/]{16}$/.test(q.iv)&&typeof q.ciphertext==='string'&&q.ciphertext.length>=24&&q.ciphertext.length<=10000&&/^[A-Za-z0-9+/]+={0,2}$/.test(q.ciphertext);
}
export function validBody(d){
 if(!d||typeof d!=='object')return false;
 if(d.type==='probe')return Object.keys(d).length===1;
 return Object.keys(d).sort().join(',')==='encrypted_request,request_id,type'&&d.type==='sync'&&ID.test(d.request_id)&&envelope(d.encrypted_request);
}
export async function verify(secret,ts,raw,sig,now=Date.now()){
 if(!HEX.test(secret||'')||!/^\d{10}$/.test(ts||'')||!HEX.test(sig||'')||Math.abs(Math.floor(now/1000)-Number(ts))>120)return false;
 const k=await crypto.subtle.importKey('raw',fromHex(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);
 return crypto.subtle.verify('HMAC',k,fromHex(sig),enc.encode(ts+'\n'+raw));
}
async function bounded(request){
 const reader=request.body?.getReader();if(!reader)throw Error('body');
 let total=0;const chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>MAX){await reader.cancel();throw Error('size')}chunks.push(value)}
 const out=new Uint8Array(total);let i=0;for(const c of chunks){out.set(c,i);i+=c.length}
 return new TextDecoder('utf-8',{fatal:true}).decode(out);
}
function ghHeaders(token,write=false){return {'Authorization':'Bearer '+token.trim(),'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'northstar-watchlist-sync-v12',...(write?{'Content-Type':'application/json'}:{})}}
const workflow='https://api.github.com/repos/'+REPO+'/actions/workflows/431516961';
async function ghFetch(url,token,options={},ms=10000,fetcher=fetch){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),ms);
 try{return await fetcher(url,{...options,headers:ghHeaders(token,options.method==='POST'),redirect:'manual',signal:c.signal})}
 finally{clearTimeout(timer)}
}
function upstream(stage,r){return json({error:'upstream',stage,github_status:r.status},502)}
function network(stage,e){return json({error:'upstream',stage,network_error:e?.name==='AbortError'||e?.name==='TimeoutError'?'timeout':'transport'},502)}
export async function dispatch(token,d,fetcher=fetch){
 const r=await ghFetch(workflow+'/dispatches',token,{method:'POST',body:JSON.stringify({ref:'main',inputs:{mode:'sync',encrypted_request:JSON.stringify(d.encrypted_request)},return_run_details:true})},12000,fetcher);
 if(r.status===204)return {state:'accepted',run_id:null};
 if(r.status===200){const x=await r.json();return {state:'accepted',run_id:Number.isSafeInteger(x.workflow_run_id)&&x.workflow_run_id>0?x.workflow_run_id:null}}
 if([400,401,403,404,422,429].includes(r.status))return {state:'rejected'};
 return {state:'unknown'};
}
export default {async fetch(request,env){
 const u=new URL(request.url);
 if(u.pathname!=='/v1/watchlist')return fail('invalid',404);
 if(request.headers.get('Origin')!==ORIGIN)return fail('unauthorized',403);
 if(request.method==='OPTIONS')return new Response(null,{status:204,headers:{...headers,'access-control-allow-methods':'POST, OPTIONS','access-control-allow-headers':'content-type,x-sync-time,x-sync-signature','access-control-max-age':'600'}});
 if(request.method!=='POST')return fail('invalid',405);
 if(!HEX.test(env.SYNC_AUTH_KEY||'')||!env.GITHUB_DISPATCH_TOKEN||!env.SYNC_GATE)return fail('not_configured',503);
 let raw,d;try{raw=await bounded(request);d=JSON.parse(raw);if(!validBody(d))throw Error('format')}catch{return fail('invalid',400)}
 try{if(!await verify(env.SYNC_AUTH_KEY,request.headers.get('X-Sync-Time'),raw,request.headers.get('X-Sync-Signature')))return fail('unauthorized',401)}catch{return fail('unauthorized',401)}
 if(d.type==='probe'){
  try{const r=await ghFetch(workflow,env.GITHUB_DISPATCH_TOKEN,{},10000);if(!r.ok)return upstream('workflow',r);const d=await r.json();if(d.id!==431516961||d.state!=='active')return json({error:'upstream',stage:'workflow_metadata'},502);return json({state:'configured',version:2})}catch(e){return network('workflow',e)}
 }
 try{return await env.SYNC_GATE.get(env.SYNC_GATE.idFromName('owner')).fetch('https://internal/sync',{method:'POST',body:raw})}catch{return fail('unknown',503)}
}};
/* Durable Object serializes owner submissions and persists idempotency before side effects. */
export class SyncGate{
 constructor(ctx,env){this.ctx=ctx;this.env=env}
 async fetch(request){
  const raw=await request.text(),d=JSON.parse(raw),hash=toHex(await crypto.subtle.digest('SHA-256',enc.encode(raw)));
  return this.ctx.blockConcurrencyWhile(async()=>{
   const now=Date.now(),old=(await this.ctx.storage.get('recent'))||[];
   const recent=old.filter(x=>now-x.at<86400000).slice(-64),prior=recent.find(x=>x.id===d.request_id);
   if(prior){
    if(prior.hash!==hash)return fail('invalid',400);
    if(prior.state==='accepted')return json({state:'accepted',run_id:prior.run_id,duplicate:true});
    if(prior.state==='rejected')return fail('rejected',502);
    return fail('unknown',409);
   }
   if(recent.some(x=>now-x.at<60000))return fail('busy',409);
   try{
    const active=await ghFetch(workflow+'/runs?branch=main&per_page=20',this.env.GITHUB_DISPATCH_TOKEN,{},10000);
    if(!active.ok)return upstream('workflow_runs',active);
    const v=await active.json();if(!Array.isArray(v.workflow_runs))return fail('upstream',502);
    if(v.workflow_runs.some(x=>x.status!=='completed'))return fail('busy',409);
   }catch(e){return network('workflow_runs',e)}
   const record={id:d.request_id,hash,at:now,state:'unknown',run_id:null};
   recent.push(record);await this.ctx.storage.put('recent',recent);
   let result;try{result=await dispatch(this.env.GITHUB_DISPATCH_TOKEN,d)}catch{return fail('unknown',503)}
   Object.assign(record,result);await this.ctx.storage.put('recent',recent);
   return result.state==='accepted'?json({state:'accepted',run_id:result.run_id}):fail(result.state==='rejected'?'rejected':'unknown',502);
  })
 }
}
