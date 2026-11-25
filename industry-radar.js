'use strict';
/* Radar is isolated from the portfolio state; no personal positions are sent. */
(function(){
 const DB='northstar-radar-key-v1', SECRET_LINK='https://github.com/winterous-bot/investment-cockpit/settings/secrets/actions/new';
 let key=null,dbPromise=null,plain=null,asof=null,loading=false,epoch=0,notice='';
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
  const f=byId('radarFrame');if(!f||!plain)return;
  // Render decrypted research HTML in an opaque sandbox. No same-origin or network access.
  const csp='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">';
  f.srcdoc=plain.replace(/^<!doctype html>/i,'<!doctype html>'+csp);f.hidden=false;
 }
 function dateText(d){return d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6)}
 async function refresh(){
  if(loading)return;const t=epoch;loading=true;
  try{
   if(!key)key=await readKey();
   if(t!==epoch)return;
   if(!key){setStatus('首次使用：请配置独立雷达密钥。');return;}
   setStatus('正在读取最新加密快照…');
   const response=await fetch('./data/industry_radar.enc.json?ts='+Date.now(),{cache:'no-store'});
   if(response.status===404){setStatus('尚无已发布快照。请先配置GitHub Secret并运行更新任务。');return;}
   if(!response.ok)throw Error('HTTP '+response.status);
   const x=await response.json();
   if(x.version!==1||!/^\d{8}$/.test(x.asof)||typeof x.iv!=='string'||typeof x.ciphertext!=='string'||x.ciphertext.length>10000000)throw Error('快照格式异常');
   const iv=decode(x.iv);if(iv.length!==12)throw Error('快照校验失败');
   let data;try{data=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-radar-v1:'+x.asof),tagLength:128},key,decode(x.ciphertext))}catch{throw Error('无法解密：请核对本机密钥与GitHub RADAR_KEY是否一致')}
   const html=new TextDecoder().decode(data);if(!html.startsWith('<!doctype html>'))throw Error('快照内容异常');
   if(t!==epoch)return;
   if(asof&&x.asof<asof){setStatus('已保留较新的快照 '+dateText(asof));return;}
   plain=html;asof=x.asof;
   const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
   setStatus('行情日期 '+dateText(asof)+' · 北京时间'+(dateText(asof)!==today?' · 非今日行情，请核对交易日':''));
   showFrame();
  }catch(e){if(t===epoch)setStatus((plain?'已保留 '+dateText(asof)+' 快照；':'')+e.message)}
  finally{loading=false;}
 }
 function setup(){
  const root=byId('radarRoot');if(!root)return;
  const inp=byId('radarKeyInput');
  byId('radarGenerate').onclick=()=>{if(key&&!confirm('已配置密钥。更换需同步修改GitHub Secret，确定生成新密钥？'))return;inp.value=Array.from(crypto.getRandomValues(new Uint8Array(32)),x=>x.toString(16).padStart(2,'0')).join('');inp.type='text';inp.select();setStatus('请复制新密钥并保存到密码管理器，再配置GitHub Secret及本机密钥。')};
  byId('radarCopy').onclick=async()=>{if(!inp.value)return;try{await navigator.clipboard.writeText(inp.value);setStatus('密钥已复制，请仅粘贴至GitHub Secret。')}catch{inp.type='text';inp.select();setStatus('请长按选择并复制密钥。')}};
  byId('radarSave').onclick=async()=>{try{const v=await importKey(inp.value.trim());await storeKey(v);key=v;epoch++;plain=null;asof=null;byId('radarFrame').hidden=true;inp.value='';inp.type='password';setStatus('已保存本机密钥；读取最新快照。');refresh()}catch(e){setStatus(e.message)}};
  byId('radarClear').onclick=async()=>{if(!confirm('仅删除本机雷达密钥，不影响持仓和后台任务？'))return;try{await storeKey(null);key=null;plain=null;asof=null;epoch++;inp.value='';byId('radarFrame').srcdoc='';byId('radarFrame').hidden=true;setStatus('已删除本机雷达密钥。')}catch(e){setStatus(e.message)}};
  byId('radarReload').onclick=refresh;showFrame();refresh();
 }
 function page(){return '<div id="radarRoot"><div class="intro-top"><div><div class="eyebrow">INDUSTRY RESEARCH / V1.1</div><h1 class="page-title">行业热点雷达</h1><div class="subtle">交易日21:10计划更新 · 仅供个人研究</div></div></div><section class="panel" style="margin-top:14px"><div id="radarStatus" class="muted-note" role="status">'+esc(notice||'读取本机密钥…')+'</div><button id="radarReload" class="button secondary block" style="margin-top:10px">刷新最新雷达</button><details style="margin-top:12px"><summary>首次配置／更换雷达密钥</summary><p class="muted-note">生成随机密钥，复制并保存到密码管理器。在GitHub添加名为 RADAR_KEY 的 Actions Secret，值为同一密钥；再点击保存本机密钥。请勿发送给他人或粘贴到聊天、代码和URL中。密钥与Tushare Token无关。</p><div class="field"><label for="radarKeyInput">64位十六进制密钥</label><input id="radarKeyInput" type="password" autocomplete="off" autocapitalize="off" spellcheck="false"></div><div class="action-toolbar"><button id="radarGenerate" class="button secondary">生成随机密钥</button><button id="radarCopy" class="button secondary">复制密钥</button><button id="radarSave" class="button">保存本机密钥</button></div><p><a href="'+SECRET_LINK+'" target="_blank" rel="noopener noreferrer">打开GitHub Secret配置</a></p><button id="radarClear" class="button quiet">清除本机雷达密钥</button></details></section><iframe id="radarFrame" title="行业热点雷达数据" sandbox="allow-scripts" referrerpolicy="no-referrer" style="width:100%;height:76vh;border:0;border-radius:12px;margin-top:12px;background:transparent" hidden></iframe><button class="button quiet block" data-tab-jump="overview">返回总览</button></div>'}
 const baseRender=render;
 render=function(){if(activeTab!=='radar')return baseRender();if(byId('radarRoot'))return;byId('app').innerHTML=page();all('.nav-link').forEach(x=>{x.classList.remove('active');x.setAttribute('aria-current','false')});setup()};
 const baseOverview=renderOverview;
 renderOverview=function(){return '<section class="panel" style="margin:12px 0"><div class="row-between"><b>行业热点雷达 V1.1</b><span class="pill">研究</span></div><p class="muted-note">行业强度、成交异动、量价前兆、广度及领涨股</p><button class="button secondary block" data-tab-jump="radar">进入行业热点雷达</button></section>'+baseOverview()};
 if(activeTab==='overview')render();
})();
