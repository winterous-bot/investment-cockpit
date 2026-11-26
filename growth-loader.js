'use strict';
(function(){
 const status=document.getElementById('growthStatus'),root=document.getElementById('growthMain'),reload=document.getElementById('growthReload');
 const bytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
 let loading=false,last=null,lastDate=null,lastCipher=null,lastVisibleCheck=0;
 function readKey(){return new Promise((resolve,reject)=>{const r=indexedDB.open('northstar-radar-key-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('keys');r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result;try{const t=db.transaction('keys','readonly'),q=t.objectStore('keys').get('radar');q.onsuccess=()=>resolve(q.result||null);q.onerror=()=>reject(q.error);t.oncomplete=()=>db.close();t.onabort=()=>db.close()}catch(e){db.close();reject(e)}}})}
 async function fixedKey(){let timer;try{const k=await Promise.race([readKey(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('本机密钥读取超时')),2500)})]);if(k)return k}catch(_){}finally{clearTimeout(timer)}try{const h=localStorage.getItem('northstar-radar-fixed-key-v1');if(/^[0-9a-fA-F]{64}$/.test(h||''))return crypto.subtle.importKey('raw',Uint8Array.from(h.match(/../g),x=>parseInt(x,16)),'AES-GCM',false,['decrypt'])}catch(_){}return null}
 async function decode(q,key){
  if(q.version!==2||q.codec!=='gzip'||!/^\d{8}$/.test(q.asof)||typeof q.iv!=='string'||typeof q.ciphertext!=='string'||q.ciphertext.length>20000000)throw Error('快照格式错误');
  const iv=bytes(q.iv);if(iv.length!==12)throw Error('IV格式错误');
  const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-growth-prod-v2:'+q.asof),tagLength:128},key,bytes(q.ciphertext));
  if(typeof DecompressionStream!=='function')throw Error('浏览器不支持解压，请升级系统浏览器');
  const rd=new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();let size=0,parts=[];
  while(true){const {done,value}=await rd.read();if(done)break;size+=value.length;if(size>80*1024*1024){await rd.cancel();throw Error('快照解压体积超限')}parts.push(value)}
  const d=JSON.parse(await new Blob(parts).text()),r=d.report;
  if(r?.version!=='growth-scanner-v1.4.2'||r.asof!==q.asof||r.quote_date!==q.asof||r.model_frozen!==true||r.data_coverage_pass!==true||!Array.isArray(d.rows)||d.rows.length!==r.complete_metrics||d.rows.length>7000||d.rows.length<1||!Array.isArray(r.presets)||r.presets.length!==3)throw Error('数据版本、日期或覆盖校验失败');
  return d;
 }
 async function refresh(force=false){
  if(loading)return;lastVisibleCheck=Date.now();loading=true;reload.disabled=true;
  try{
   const key=await fixedKey();if(!key){root.hidden=true;last=null;lastDate=null;lastCipher=null;throw Error('尚未配置固定密钥，请在行业雷达设置中保存原密钥；无需新密钥')}
   await window.NorthstarSnapshots.load('growth',{
    force,decode:q=>decode(q,key),
    show:(d,q)=>{if(lastDate&&q.asof<lastDate)return;if(lastCipher!==q.ciphertext||root.hidden){window.NorthstarGrowthView.mount(d);last=d;lastDate=d.report.asof;lastCipher=q.ciphertext}},
    notify:(msg,q)=>{const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','');status.textContent=(q?'行情日期 '+q.asof+(last?.report?.periods?.latest?' · 财报期 '+last.report.periods.latest:'')+(today!==q.asof?' · 非今日行情':'')+' · 北京时间 · ':'')+msg}
   });
  }catch(e){status.textContent=(last?'保留已验证快照 '+lastDate+'；':'')+e.message}
  finally{loading=false;reload.disabled=false}
 }
 reload.onclick=()=>refresh(true);refresh();
 if(document.addEventListener)document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&Date.now()-lastVisibleCheck>=15*60*1000)refresh()});
 if('serviceWorker' in navigator&&location.protocol==='https:')navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).catch(()=>{});
})();
