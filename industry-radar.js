'use strict';
/* Radar is isolated from the portfolio state; no personal positions are sent. */
(function(){
 const DB='northstar-radar-key-v1', BACKUP='northstar-radar-fixed-key-v1', SECRET_LINK='https://github.com/winterous-bot/investment-cockpit/settings/secrets/actions/new';
 let key=null,dbPromise=null,plain=null,asof=null,loading=false,epoch=0,notice='',lastCipher=null,lastVisibleCheck=0;
 const byId=x=>document.getElementById(x);
 function db(){
  if(!dbPromise)dbPromise=new Promise((resolve,reject)=>{
   const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore('keys');
   r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);
  });
  return dbPromise;
 }
 async function readKey(){const d=await db();return new Promise((res,rej)=>{const t=d.transaction('keys','readonly');const r=t.objectStore('keys').get('radar');r.onsuccess=()=>res(r.result||null);r.onerror=()=>rej(r.error)})}
 async function storeKey(value){const d=await db();return new Promise((res,rej)=>{const t=d.transaction('keys','readwrite');if(value)t.objectStore('keys').put(value,'radar');else t.objectStore('keys').delete('radar');t.oncomplete=()=>res();t.onerror=()=>rej(t.error);t.onabort=()=>rej(t.error)})}
 const decode=x=>Uint8Array.from(atob(x),c=>c.charCodeAt(0));
 async function importKey(hex){
  if(!/^[0-9a-fA-F]{64}$/.test(hex))throw Error('请使用页面生成的64位十六进制密钥');
  return crypto.subtle.importKey('raw',Uint8Array.from(hex.match(/../g),h=>parseInt(h,16)),'AES-GCM',false,['decrypt']);
 }
 async function loadFixedKey(){
  // Keep the original IndexedDB namespace across every release.
  try{const stored=await readKey();if(stored)return stored}catch(_){}
  // Optional device-local recovery copy, never transmitted or included in app backups.
  try{const hex=localStorage.getItem(BACKUP);if(hex){const v=await importKey(hex);try{await storeKey(v)}catch(_){}return v}}catch(_){}
  return null;
 }
 async function remember(hex,v,backup){
  let saved=false;
  try{await storeKey(v);saved=true}catch(_){}
  try{if(backup){localStorage.setItem(BACKUP,hex);saved=true}else localStorage.removeItem(BACKUP)}catch(_){}
  if(!saved)throw Error('本机无法持久保存密钥，请检查浏览器存储设置');
  try{if(navigator.storage?.persist)await navigator.storage.persist()}catch(_){}
 }
 function setStatus(t){notice=t;const e=byId('radarStatus');if(e)e.textContent=t}
 function showFrame(){
  const host=byId('radarContent');if(!host||!plain)return;
  window.NorthstarRadarView.mount(host,plain,{level:host.dataset.level,mode:host.dataset.mode});
 }
 function clearView(){byId('radarContent').replaceChildren();lastCipher=null;}
 function settings(open){byId('radarSettings').hidden=!open;byId('settingsToggle').setAttribute('aria-expanded',String(open));}
 function dateText(d){return d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6)}
 async function refresh(force=false){
  if(loading)return;lastVisibleCheck=Date.now();const t=epoch;loading=true;byId('radarReload').disabled=true;
  try{
   if(!key){const saved=await loadFixedKey();if(t!==epoch)return;key=saved;}
   if(t!==epoch)return;
   if(!key){setStatus('首次使用：请配置独立雷达密钥。');settings(true);clearView();return;}
   const dateStatus=(msg,q)=>{if(t!==epoch)return;const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());setStatus((q?'行情日期 '+dateText(q.asof)+' · 北京时间'+(dateText(q.asof)!==today?' · 非今日行情':'')+' · ':'')+msg)};
   await window.NorthstarSnapshots.load('radar',{
    force,active:()=>t===epoch&&!!key,
    decode:async q=>{
     if(q.version!==1||!/^\d{8}$/.test(q.asof)||typeof q.iv!=='string'||typeof q.ciphertext!=='string'||q.ciphertext.length>10000000)throw Error('快照格式异常');
     const iv=decode(q.iv);if(iv.length!==12)throw Error('快照校验失败');
     const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-radar-v1:'+q.asof),tagLength:128},key,decode(q.ciphertext));
     return window.NorthstarRadarView.extract(new TextDecoder().decode(raw),q.asof);
    },
    show:(d,q)=>{if(t!==epoch||asof&&q.asof<asof)return;const changed=lastCipher!==q.ciphertext;plain=d;asof=q.asof;lastCipher=q.ciphertext;if(changed||!byId('radarContent').children.length)showFrame()},
    notify:dateStatus
   });
  }catch(e){if(t===epoch)setStatus((plain?'已保留 '+dateText(asof)+' 快照；':'')+e.message)}
  finally{loading=false;byId('radarReload').disabled=false;if(t!==epoch&&key&&byId('radarRoot'))refresh(true);}
 }
 function setup(){
  const root=byId('radarRoot');if(!root)return;
  const inp=byId('radarKeyInput');
  byId('radarGenerate').onclick=()=>{if(key&&!confirm('已有固定密钥。除非密钥泄漏，否则无需更换。确定生成新密钥？'))return;inp.value=Array.from(crypto.getRandomValues(new Uint8Array(32)),x=>x.toString(16).padStart(2,'0')).join('');inp.type='text';inp.select();setStatus('只在首次配置时生成；此后长期使用同一个固定密钥。请保存到密码管理器，并同步至GitHub Secret。')};
  byId('radarCopy').onclick=async()=>{if(!inp.value)return;try{await navigator.clipboard.writeText(inp.value);setStatus('密钥已复制，请仅粘贴至GitHub Secret。')}catch{inp.type='text';inp.select();setStatus('请长按选择并复制密钥。')}};
  byId('radarSave').onclick=async()=>{try{const v=await importKey(inp.value.trim());await remember(inp.value.trim(),v,byId('radarRemember').checked);key=v;epoch++;plain=null;asof=null;clearView();await window.NorthstarSnapshots.clear();inp.value='';inp.type='password';settings(false);setStatus('已保存本机密钥；读取最新快照。');refresh(true)}catch(e){setStatus(e.message)}};
  byId('radarClear').onclick=async()=>{if(!confirm('清除本机固定密钥、所有研究模块缓存及未同步观察池草稿？不影响后台及其他设备。'))return;try{let cleared=false;try{await storeKey(null);cleared=true}catch(_){}try{localStorage.removeItem(BACKUP);cleared=true}catch(_){}if(!cleared)throw Error('无法清除本机密钥存储');key=null;plain=null;asof=null;epoch++;inp.value='';clearView();await window.NorthstarSnapshots.clear();try{localStorage.removeItem('northstar-watchlist-draft-v11');sessionStorage.removeItem('northstar-watchlist-handoff-v11')}catch(_){}setStatus('已删除本机雷达密钥。')}catch(e){setStatus(e.message)}};
  byId('settingsToggle').onclick=()=>settings(byId('radarSettings').hidden);byId('radarReload').onclick=()=>refresh(true);if(location.search&&new URLSearchParams(location.search).get('settings')==='1')settings(true);refresh();if(document.addEventListener)document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&Date.now()-lastVisibleCheck>=15*60*1000)refresh()});
 }
 setup();
 if('serviceWorker' in navigator&&location.protocol==='https:'){
  navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).catch(()=>{});
 }
})();
