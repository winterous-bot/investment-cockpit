'use strict';
/* Radar is isolated from the portfolio state; no personal positions are sent. */
(function(){
 const DB='northstar-radar-key-v1', SECRET_LINK='https://github.com/winterous-bot/investment-cockpit/settings/secrets/actions/new';
 let key=null,dbPromise=null,plain=null,asof=null,loading=false,epoch=0,notice='',lastCipher=null;
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
 function setStatus(t){notice=t;const e=byId('radarStatus');if(e)e.textContent=t}
 function showFrame(){
  const host=byId('radarContent');if(!host||!plain)return;
  window.NorthstarRadarView.mount(host,plain,{level:host.dataset.level,mode:host.dataset.mode});
 }
 function clearView(){byId('radarContent').replaceChildren();lastCipher=null;}
 function settings(open){byId('radarSettings').hidden=!open;byId('settingsToggle').setAttribute('aria-expanded',String(open));}
 function dateText(d){return d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6)}
 async function refresh(){
  if(loading)return;const t=epoch;loading=true;
  try{
   if(!key){const saved=await readKey();if(t!==epoch)return;key=saved;}
   if(t!==epoch)return;
   if(!key){setStatus('首次使用：请配置独立雷达密钥。');settings(true);clearView();return;}
   setStatus('正在读取最新加密快照…');
   const urls=['https://raw.githubusercontent.com/winterous-bot/investment-cockpit/main/data/industry_radar.enc.json','./data/industry_radar.enc.json'];
   // Pages builds are not necessarily triggered by GITHUB_TOKEN pushes; use raw ciphertext first.
   let response=null,lastError=null;
   for(const u of urls){try{const c=new AbortController(),timer=setTimeout(()=>c.abort(),7000);let r;try{r=await fetch(u+'?ts='+Date.now(),{cache:'no-store',signal:c.signal})}finally{clearTimeout(timer)}if(r.ok){response=r;break}if(!response||r.status!==404)response=r;}catch(e){lastError=e}}
   if(!response)throw Error('无法连接雷达数据源，请稍后刷新');
   if(response.status===404){setStatus('尚无已发布快照。请先配置GitHub Secret并运行更新任务。');return;}
   if(!response.ok)throw Error('HTTP '+response.status);
   const x=await response.json();
   if(x.version!==1||!/^\d{8}$/.test(x.asof)||typeof x.iv!=='string'||typeof x.ciphertext!=='string'||x.ciphertext.length>10000000)throw Error('快照格式异常');
   const iv=decode(x.iv);if(iv.length!==12)throw Error('快照校验失败');
   let data;try{data=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-radar-v1:'+x.asof),tagLength:128},key,decode(x.ciphertext))}catch{throw Error('无法解密：请核对本机密钥与GitHub RADAR_KEY是否一致')}
   const html=new TextDecoder().decode(data);const parsed=window.NorthstarRadarView.extract(html,x.asof);
   if(t!==epoch)return;
   if(asof&&x.asof<asof){setStatus('已保留较新的快照 '+dateText(asof));return;}
   const changed=lastCipher!==x.ciphertext;plain=parsed;asof=x.asof;lastCipher=x.ciphertext;
   const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
   setStatus('行情日期 '+dateText(asof)+' · 北京时间'+(dateText(asof)!==today?' · 非今日行情，请核对交易日':''));
   if(changed||!byId('radarContent').children.length)showFrame();
  }catch(e){if(t===epoch)setStatus((plain?'已保留 '+dateText(asof)+' 快照；':'')+e.message)}
  finally{loading=false;if(t!==epoch&&key&&byId('radarRoot'))refresh();}
 }
 function setup(){
  const root=byId('radarRoot');if(!root)return;
  const inp=byId('radarKeyInput');
  byId('radarGenerate').onclick=()=>{if(key&&!confirm('已配置密钥。更换需同步修改GitHub Secret，确定生成新密钥？'))return;inp.value=Array.from(crypto.getRandomValues(new Uint8Array(32)),x=>x.toString(16).padStart(2,'0')).join('');inp.type='text';inp.select();setStatus('请复制新密钥并保存到密码管理器，再配置GitHub Secret及本机密钥。')};
  byId('radarCopy').onclick=async()=>{if(!inp.value)return;try{await navigator.clipboard.writeText(inp.value);setStatus('密钥已复制，请仅粘贴至GitHub Secret。')}catch{inp.type='text';inp.select();setStatus('请长按选择并复制密钥。')}};
  byId('radarSave').onclick=async()=>{try{const v=await importKey(inp.value.trim());await storeKey(v);key=v;epoch++;plain=null;asof=null;clearView();inp.value='';inp.type='password';settings(false);setStatus('已保存本机密钥；读取最新快照。');refresh()}catch(e){setStatus(e.message)}};
  byId('radarClear').onclick=async()=>{if(!confirm('仅删除本机雷达密钥，不影响后台任务和旧版本本机数据？'))return;try{await storeKey(null);key=null;plain=null;asof=null;epoch++;inp.value='';clearView();setStatus('已删除本机雷达密钥。')}catch(e){setStatus(e.message)}};
  byId('settingsToggle').onclick=()=>settings(byId('radarSettings').hidden);byId('radarReload').onclick=refresh;refresh();
 }
 setup();
 if('serviceWorker' in navigator&&location.protocol==='https:'){
  navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).catch(()=>{});
 }
})();
