'use strict';
/* One authenticated encrypted snapshot per module. No plaintext or keys in this DB. */
(function(root){
 const DB='northstar-encrypted-snapshots-v1',STORE='snapshots',TTL=15*60*1000,RETRY=15*60*1000;
 const files={radar:'industry_radar.enc.json',growth:'growth.enc.json',watchlist:'watchlist.enc.json',directory:'company-directory.enc.json'};
 const pathFor=id=>Object.prototype.hasOwnProperty.call(files,id)?files[id]:/^company:[0-9a-f]{64}$/.test(id)?'companies/'+id.slice(8)+'.enc.json':null;
 const validRev=r=>typeof r==='string'&&/^[0-9a-f]{40}$/.test(r);
 const envelope=q=>q&&/^\d{8}$/.test(q.asof)&&typeof q.iv==='string'&&typeof q.ciphertext==='string';
 const raw='https://raw.githubusercontent.com/winterous-bot/investment-cockpit/';
 const api='https://api.github.com/repos/winterous-bot/investment-cockpit/commits?sha=main&per_page=1&path=';
 function storage(){
  let pending=null;
  function db(){
   if(!pending)pending=new Promise((resolve,reject)=>{
    let r,expired=false;try{r=indexedDB.open(DB,1)}catch(e){reject(e);return}
    const fail=e=>{expired=true;clearTimeout(timer);reject(e)},timer=setTimeout(()=>fail(Error('storage open timeout')),2500);
    r.onupgradeneeded=()=>r.result.createObjectStore(STORE);
    r.onsuccess=()=>{clearTimeout(timer);if(expired){r.result.close();return}r.result.onversionchange=()=>{r.result.close();pending=null};resolve(r.result)};
    r.onerror=()=>fail(r.error||Error('storage error'));
    r.onblocked=()=>fail(Error('storage blocked'));
   }).catch(e=>{pending=null;throw e});
   return pending;
  }
  async function tx(mode,fn){
   const d=await db();return new Promise((resolve,reject)=>{
    let t;try{t=d.transaction(STORE,mode)}catch(e){reject(e);return}
    let result; t.oncomplete=()=>resolve(result);t.onerror=t.onabort=()=>reject(t.error||Error('storage transaction failed'));
    try{fn(t.objectStore(STORE),v=>result=v)}catch(e){try{t.abort()}catch(_){}reject(e)}
   });
  }
  return {
   get:id=>tx('readonly',(s,done)=>{const r=s.get(id);r.onsuccess=()=>done(r.result||null)}),
   // Atomic date and request ordering check protects against competing tabs.
   put:(id,rec)=>tx('readwrite',(s,done)=>{const r=s.get(id);r.onsuccess=()=>{
    const old=r.result;
    if(old&&envelope(old.snapshot)&&(old.snapshot.asof>rec.snapshot.asof||(old.snapshot.asof===rec.snapshot.asof&&(old.requestedAt||0)>rec.requestedAt))){done(false);return}
    s.put(rec,id);done(true)
   }}),
   clear:()=>tx('readwrite',(s,done)=>{s.clear();done(true)})
  };
 }
 function create({store=storage(),fetcher=(...a)=>fetch(...a),now=()=>Date.now()}={}){
  const memory=new Map(),attempts=new Map(),generation={n:0};
  let clearing=Promise.resolve();
  const safeGet=async id=>{try{const a=await store.get(id),b=memory.get(id);return !a?b||null:!b?a:(a.snapshot.asof>b.snapshot.asof||(a.snapshot.asof===b.snapshot.asof&&(a.requestedAt||0)>=(b.requestedAt||0)))?a:b}catch(_){return memory.get(id)||null}};
  async function get(url,ms){const c=new AbortController(),timer=setTimeout(()=>c.abort(),ms);try{const r=await fetcher(url,{cache:'no-store',signal:c.signal});if(!r.ok)throw Error('HTTP '+r.status);return await r.json()}finally{clearTimeout(timer)}}
  async function load(id,{decode,show,notify,force=false,active=()=>true}){
   const file=pathFor(id);if(!file)throw Error('未知研究模块');
   const gen=generation.n,alive=()=>gen===generation.n&&active();
   await clearing;
   if(!alive())return;
   const requestedAt=now();let rec=await safeGet(id),local=null;
   if(!alive())return;
   if(rec&&envelope(rec.snapshot)){
    try{local=await decode(rec.snapshot);if(!alive())return;show(local,rec.snapshot,'local');notify('本地数据已加载',rec.snapshot)}catch(_){local=null;rec=null}
   }else rec=null;
   if(!alive())return;
   if(local&&!force&&requestedAt-(rec.checkedAt||0)<TTL&&requestedAt>=rec.checkedAt){notify('本地数据 · 15分钟内已核对版本',rec.snapshot);return}
   if(local&&!force&&requestedAt-(rec.attemptedAt||0)<RETRY&&requestedAt>=rec.attemptedAt){notify('本地数据 · 等待下次版本检查（上次检查未完成或失败）',rec.snapshot);return}
   if(local&&!force&&attempts.has(id)&&requestedAt-attempts.get(id)<RETRY){notify('本地数据 · 等待下次版本检查',rec.snapshot);return}
   attempts.set(id,requestedAt);
   // Persist only a timestamp change for a locally authenticated record. Keep original revision and ordering.
   if(local){try{await store.put(id,{...rec,attemptedAt:requestedAt});}catch(_){}if(!alive())return;}
   notify(local?'本地数据 · 正在检查服务器版本':'首次读取加密快照…',rec?.snapshot);
   let rev=null,versionError='';
   const path='data/'+file;
   try{const v=await get(api+encodeURIComponent(path)+'&_='+now(),6000);if(validRev(v?.[0]?.sha))rev=v[0].sha;else throw Error('版本信息异常')}catch(e){versionError=e.message}
   if(!alive())return;
   async function save(next){
    if(!alive())return false;
    let persisted=false;
    // Store only the validated ciphertext and small version metadata.
    try{persisted=await store.put(id,next);if(!alive())return false;if(!persisted)return false}catch(_){}
    memory.set(id,next);
    return persisted?'disk':'memory';
   }
   if(local&&rev&&rec.rev===rev){
    const saved=await save({...rec,checkedAt:now(),attemptedAt:requestedAt,requestedAt});if(!alive())return;
    notify(saved?'服务器版本未变化 · 无需下载':'本地数据 · 服务器版本未变化',rec.snapshot);return
   }
   // Never re-download MB-sized data on a metadata failure when a valid local snapshot exists.
   if(local&&!rev){notify('版本检查失败，保留本地数据（'+versionError+'）',rec.snapshot);return}
   const urls=rev?[{url:raw+rev+'/'+path,rev}]:[];
   urls.push({url:'./'+path+'?ts='+now(),rev:null},{url:raw+'main/'+path+'?ts='+now(),rev:null});
   let best=null,err='数据尚未发布',auth=false;
   for(const source of urls){
    if(!alive())return;
    try{
     const q=await get(source.url,id==='growth'?45000:20000);
     if(!envelope(q))throw Error('快照格式异常');
     const d=await decode(q);if(!alive())return;
     if(!best||q.asof>best.q.asof)best={q,d,rev:source.rev};
     if(source.rev)break;
     // A first authenticated fallback is sufficient; never download all large mirrors.
     if(!local||q.asof>=rec.snapshot.asof)break;
    }catch(e){err=e.message||'网络异常';if(e.name==='OperationError')auth=true}
   }
   if(!alive())return;
   if(!best){
    const why=auth?'固定密钥未通过认证，请核对原密钥，不要生成新密钥':err;
    if(local){notify('更新失败，保留本地数据：'+why,rec.snapshot);return}
    throw Error(why)
   }
   if(local&&(best.q.asof<rec.snapshot.asof||(!best.rev&&best.q.asof===rec.snapshot.asof))){notify('未确认服务器新版本，保留本地数据',rec.snapshot);return}
   // If a concurrent tab stored a newer date/request, do not replace it.
   const saved=await save({snapshot:best.q,rev:best.rev,checkedAt:best.rev?now():0,attemptedAt:requestedAt,requestedAt});
   if(!alive())return;
   if(saved===false){const latest=await safeGet(id);if(!alive())return;try{if(latest&&envelope(latest.snapshot)){const d=await decode(latest.snapshot);if(!alive())return;show(d,latest.snapshot,'local');notify('已保留较新本地数据',latest.snapshot);return}}catch(_){}}
   show(best.d,best.q,'network');
   if(saved==='disk'){try{if(typeof navigator!=='undefined'&&navigator.storage?.persist)navigator.storage.persist().catch(()=>{})}catch(_){}}
   notify(saved==='disk'?'已更新并保存本地数据':saved==='memory'?'已更新 · 本机存储不可用':'已更新',best.q);
  }
  async function clear(){generation.n++;memory.clear();attempts.clear();clearing=store.clear().catch(()=>{});await clearing}
  return {load,clear};
 }
 const manager=create();
 root.NorthstarSnapshots={...manager,create,TTL};
 if(typeof module!=='undefined'&&module.exports)module.exports={create,storage,TTL,pathFor};
})(typeof window!=='undefined'?window:globalThis);
