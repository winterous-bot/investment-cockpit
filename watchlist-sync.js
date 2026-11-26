'use strict';
(function(root){
 const DOMAIN='northstar-watchlist-sync-auth-v12', enc=new TextEncoder();
 const hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
 function endpoint(s){
  const u=new URL(s.trim());
  if(u.protocol!=='https:'||u.username||u.password||u.port||u.search||u.hash||!/^investment-watchlist-sync\.[a-z0-9-]+\.workers\.dev$/.test(u.hostname)||!['','/'].includes(u.pathname))throw Error('请输入本人部署的 investment-watchlist-sync.*.workers.dev 根网址');
  return u.origin;
 }
 async function authKey(rawHex){
  if(!/^[a-f0-9]{64}$/i.test(rawHex||''))throw Error('原固定密钥格式异常');
  const k=await crypto.subtle.importKey('raw',Uint8Array.from(rawHex.match(/../g),x=>parseInt(x,16)),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const derived=await crypto.subtle.sign('HMAC',k,enc.encode(DOMAIN));
  return crypto.subtle.importKey('raw',derived,{name:'HMAC',hash:'SHA-256'},false,['sign']);
 }
 async function signed(key,body,now=Date.now()){
  const raw=JSON.stringify(body),ts=String(Math.floor(now/1000));
  return {raw,ts,sig:hex(await crypto.subtle.sign('HMAC',key,enc.encode(ts+'\n'+raw)))};
 }
 async function send(url,key,body,fetcher=fetch){
  const s=await signed(key,body);
  const r=await fetcher(endpoint(url)+'/v1/watchlist',{method:'POST',headers:{'Content-Type':'application/json','X-Sync-Time':s.ts,'X-Sync-Signature':s.sig},body:s.raw,cache:'no-store',credentials:'omit',redirect:'error',signal:AbortSignal.timeout(25000)});
  let d;try{d=await r.json()}catch{throw Error('授权网关响应异常')}
  if(!r.ok){
   const errors={unauthorized:'签名未通过，请检查原固定密钥及网关配置',busy:'后台已有请求或正在研究，请稍后重试',not_configured:'网关尚未配置',upstream:'GitHub 暂不可用或授权失效',invalid:'请求校验失败',unknown:'上次提交结果不确定，请先检查后台'};
   const e=Error(errors[d?.error]||'网关暂不可用（HTTP '+r.status+'）');e.code=d?.error;throw e;
  }
  return d;
 }
 const api={endpoint,authKey,signed,send};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.NorthstarWatchlistSync=api;
})(typeof window!=='undefined'?window:globalThis);
