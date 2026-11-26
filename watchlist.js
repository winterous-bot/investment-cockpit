'use strict';
(function(root){
const LIMIT=20,CODE=/^\d{6}\.(SH|SZ)$/,ID=/^[0-9a-f]{64}$/,REV=/^[0-9a-f]{32}$/,DAY=/^\d{8}$/;
const DRAFT='northstar-watchlist-draft-v11',HANDOFF='northstar-watchlist-handoff-v11',BACKUP='northstar-radar-fixed-key-v1';
const enc=new TextEncoder(),dec=new TextDecoder();
const bytes=s=>Uint8Array.from(atob(s),x=>x.charCodeAt(0));
const b64=a=>{let s='';for(let i=0;i<a.length;i+=8192)s+=String.fromCharCode(...a.subarray(i,i+8192));return btoa(s)};
const day=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','');
function validCodes(a){return Array.isArray(a)&&a.length<=LIMIT&&a.every(k=>typeof k==='string'&&CODE.test(k))&&new Set(a).size===a.length}
function same(a,b){return a.length===b.length&&a.every((k,i)=>k===b[i])}
function validManifest(x,q){return x?.version==='watchlist-v1.1'&&REV.test(x.revision)&&x.asof===q.asof&&Array.isArray(x.entries)&&validCodes(x.entries.map(z=>z.code))&&x.entries.every(z=>ID.test(z.id)&&typeof z.name==='string'&&typeof z.industry==='string'&&['ready','failed','incomplete','unsupported'].includes(z.status)&&(z.report_asof===null||DAY.test(z.report_asof)))}
async function decrypt(q,key,domain){
 if(q?.version!==1||!['gzip','json'].includes(q.codec)||!DAY.test(q.asof)||typeof q.iv!=='string'||typeof q.ciphertext!=='string'||q.ciphertext.length>12000000)throw Error('快照格式异常');
 const iv=bytes(q.iv);if(iv.length!==12)throw Error('IV异常');
 const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:enc.encode(domain+':'+q.asof),tagLength:128},key,bytes(q.ciphertext));
 if(q.codec==='json')return JSON.parse(dec.decode(raw));
 if(typeof DecompressionStream!=='function')throw Error('系统不支持压缩快照');
 const rd=new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();let total=0,parts=[];
 while(true){const {done,value}=await rd.read();if(done)break;total+=value.length;if(total>32*1024*1024){await rd.cancel();throw Error('解压大小超限')}parts.push(value)}
 return JSON.parse(await new Blob(parts).text())
}
async function encrypt(obj,key,domain,date=day()){
 const iv=crypto.getRandomValues(new Uint8Array(12)),raw=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(domain+':'+date),tagLength:128},key,enc.encode(JSON.stringify(obj)));
 return {version:1,codec:'json',asof:date,iv:b64(iv),ciphertext:b64(new Uint8Array(raw))}
}
async function keyFromHex(h,usages){if(!/^[0-9a-fA-F]{64}$/.test(h||''))throw Error('请输入原64位固定密钥');return crypto.subtle.importKey('raw',Uint8Array.from(h.match(/../g),x=>parseInt(x,16)),'AES-GCM',false,usages)}
function readKey(){return new Promise((res,rej)=>{let timer=setTimeout(()=>rej(Error('本机密钥读取超时')),2500);try{const r=indexedDB.open('northstar-radar-key-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('keys');r.onblocked=r.onerror=()=>{clearTimeout(timer);rej(Error('本机密钥不可用'))};r.onsuccess=()=>{const db=r.result;try{const t=db.transaction('keys','readonly'),q=t.objectStore('keys').get('radar');q.onsuccess=()=>{clearTimeout(timer);res(q.result||null)};q.onerror=()=>{clearTimeout(timer);rej(q.error)};t.oncomplete=()=>db.close();t.onabort=()=>db.close()}catch(e){db.close();clearTimeout(timer);rej(e)}}}catch(e){clearTimeout(timer);rej(e)}})}
async function encryptionKey(hex,key){const k=await keyFromHex(hex,['encrypt','decrypt']);const q=await encrypt({check:true},k,'northstar-watchlist-local-test');const x=await decrypt(q,key,'northstar-watchlist-local-test');if(x.check!==true)throw Error('固定密钥不一致');return k}
function validDraft(x){return x?.version==='watchlist-draft-v1.1'&&REV.test(x.base)&&validCodes(x.codes)&&Array.isArray(x.labels)&&x.labels.every(z=>CODE.test(z.code)&&typeof z.name==='string'&&typeof z.industry==='string'&&x.codes.includes(z.code))&&new Set(x.labels.map(z=>z.code)).size===x.labels.length}
function reconcile(draft,manifest){
 const codes=manifest.entries.map(x=>x.code);
 if(!draft)return {draft:null,conflict:false,synced:true};
 if(same(draft.codes,codes))return {draft:null,conflict:false,synced:true};
 return {draft,conflict:draft.base!==manifest.revision,synced:false}
}
// Clear the completed search only after the local encrypted draft is saved.
async function completeSearchAdd(field,save,render){
 const query=field.value;
 if(!await save())return false;
 if(field.value===query){field.value='';field.blur();render()}
 return true;
}
const lib={validCodes,validManifest,validDraft,reconcile,encrypt,decrypt,encryptionKey,day,completeSearchAdd};
if(typeof module!=='undefined'&&module.exports){module.exports=lib;return}
root.NorthstarWatchlist=lib;
const $=id=>document.getElementById(id),el=(t,x,c)=>{const e=document.createElement(t);if(x!==undefined)e.textContent=x;if(c)e.className=c;return e};
let key=null,writeKey=null,authKey=null,remote=null,draft=null,draftError=false,dir=null,manifestBusy=false,dirBusy=false,editing=false,companyEpoch=0,current=null,lastVisibleCheck=0;
const syncApi=root.NorthstarWatchlistSync,SYNC_URL='northstar-watchlist-sync-url-v12',PENDING='northstar-watchlist-sync-pending-v12';
let pending=null,submitting=false,polling=false,syncUrl='',syncMessage='';
try{syncUrl=localStorage.getItem(SYNC_URL)||'';if(syncUrl)syncUrl=syncApi.endpoint(syncUrl);const p=JSON.parse(localStorage.getItem(PENDING)||'null');if(p&&/^[0-9a-f]{32}$/.test(p.body?.request_id)&&p.body?.type==='sync'&&p.body?.encrypted_request?.codec==='json'&&Number.isFinite(p.at))pending=p}catch(_){}
const busySync=()=>!!pending||submitting;
function savePending(p){if(p)localStorage.setItem(PENDING,JSON.stringify(p));else localStorage.removeItem(PENDING);pending=p;}
function syncNotice(s){syncMessage=s;$('syncState').textContent=s;}
function renderSync(){
 const ok=!!draft&&!!remote&&!!writeKey&&!draftError&&!reconcile(draft,remote).conflict&&!editing;
 $('oneSync').disabled=!ok||submitting||!!pending||!authKey||!syncUrl;
 $('sync').disabled=!ok||busySync();$('syncSettings').hidden=false;
 $('syncRetry').hidden=!pending||pending.state==='accepted';$('syncRetry').disabled=submitting||!authKey||!syncUrl;
 $('syncReset').hidden=!pending;$('syncReset').disabled=submitting||!pending||Date.now()-pending.at<45*60*1000;
 $('syncRun').hidden=!pending?.run_id;if(pending?.run_id)$('syncRun').href='https://github.com/winterous-bot/investment-cockpit/actions/runs/'+pending.run_id;
 $('syncState').textContent=syncMessage||(pending?'同步请求已保留，正在等待后台确认。':syncUrl?'一键同步已配置；首次请测试连接。':'首次使用需配置授权网关；仍可使用手动同步。');
 if(document.activeElement!==$('syncUrl')&&!$('syncUrl').value)$('syncUrl').value=syncUrl;
}
async function encryptedRequest(){if(!draft||!remote||draft.base!==remote.revision||!writeKey||draftError)throw Error('观察池版本不一致');const date=day();return encrypt({version:'watchlist-request-v1.1',base:remote.revision,asof:date,codes:draft.codes},writeKey,'northstar-watchlist-request-v11',date)}
async function submitOne(retry=false){
 if(submitting||!authKey||!syncUrl)return;
 submitting=true;renderPool();renderSearch();
 try{
  if(!retry){if(pending)return;const q=await encryptedRequest();const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('');savePending({at:Date.now(),state:'unknown',run_id:null,body:{type:'sync',request_id:id,encrypted_request:q}})}
  if(!pending)return;
  syncNotice('正在安全提交加密观察池…');
  const d=await syncApi.send(syncUrl,authKey,pending.body);
  if(d?.state!=='accepted')throw Error('网关未确认接收');
  const run_id=Number.isSafeInteger(d.run_id)&&d.run_id>0?d.run_id:null;
  savePending({...pending,state:'accepted',run_id});syncNotice('后台已接收；正在排队或研究，尚未完成同步。');
 }catch(e){if(e.code==='rejected'){savePending(null);syncNotice(e.message+'；本机草稿已保留，可重新提交。')}else syncNotice(e.message+'；本机草稿已保留。请先检查后台，必要时重试同一请求。')}
 finally{submitting=false;renderPool();renderSearch();if(pending)pollSync()}
}
async function pollSync(){
 if(!pending||polling||submitting||document.visibilityState==='hidden'||current)return;
 polling=true;try{
  await refresh(true);
  if(!pending)return;
  if(pending.run_id){
   const r=await fetch('https://api.github.com/repos/winterous-bot/investment-cockpit/actions/runs/'+pending.run_id,{cache:'no-store',signal:AbortSignal.timeout(6000)});
   if(r.ok){const d=await r.json();if(d.status==='completed'&&d.conclusion!=='success'){savePending(null);syncNotice('后台任务未成功（'+String(d.conclusion)+'），草稿仍在；可重新提交。');renderPool();renderSearch()}
    else if(d.status==='completed'){syncNotice('后台任务已完成，等待加密名单发布确认。')}
    else syncNotice('后台 '+(d.status==='queued'?'排队中':'研究中')+'；完成后自动检查报告。')}
  }
 }catch(_){}finally{polling=false;renderSync()}
}

const status=s=>{$('poolStatus').textContent=s};
const activeCodes=()=>draft?draft.codes:remote?remote.entries.map(x=>x.code):[];
const entry=k=>remote?.entries.find(x=>x.code===k);
function label(k){return dir?.find(x=>x.code===k)||entry(k)||draft?.labels.find(x=>x.code===k)||{code:k,name:k,industry:'待后台确认'}}
function notice(s){$('poolHint').textContent=s}
function removeDraft(){try{localStorage.removeItem(DRAFT)}catch(_){}draft=null;draftError=false}
async function saveDraft(codes,labels){
 if(!remote||!writeKey)throw Error('先取得后台观察池并授权本地编辑');
 if(!validCodes(codes))throw Error('首版最多20只沪深股票，不允许重复');
 const obj={version:'watchlist-draft-v1.1',base:draft?.base||remote.revision,codes,labels:labels.filter(x=>codes.includes(x.code))};
 if(!validDraft(obj))throw Error('观察池格式异常');
 const q=await encrypt(obj,writeKey,'northstar-watchlist-draft-v11');
 // Only publish the new local state after persistence succeeds.
 localStorage.setItem(DRAFT,JSON.stringify(q));draft=obj;draftError=false;
 if(same(codes,remote.entries.map(x=>x.code)))removeDraft();
 $('syncPanel').hidden=true;$('syncRequest').value='';
 renderPool();renderSearch()
}
function action(label,fn){const b=el('button',label);b.type='button';b.onclick=fn;return b}
const reasonText={not_currently_listed_shsz:'不在当前沪深上市名录',ttm_core_missing:'核心TTM财务数据不完整',same_day_quote_unverified:'当日行情未通过核验',public_filing_check_failed:'年报核对不一致',vendor_api_error:'数据接口异常',statement_or_calculation_unavailable:'报表类型或计算条件不适用'};
function renderPool(){
 $('poolPanel').hidden=!remote||!!current;$('searchPanel').hidden=!remote||!!current;$('keyPanel').hidden=!remote||!!current||!!writeKey;
 if(!remote||current)return;
 const state=reconcile(draft,remote),codes=activeCodes();
 $('poolCount').textContent='观察池 '+codes.length+'/'+LIMIT;
 $('poolSyncState').textContent=draftError?'本机草稿无法解密，需明确采用后台清单后再编辑':state.conflict?'后台清单已经变化，本机草稿不能直接覆盖':state.synced?'已与后台清单一致':'本机有未同步修改';
 if(state.conflict||state.synced){$('syncPanel').hidden=true;$('syncRequest').value=''}
 $('adopt').hidden=!draft&&!draftError;$('adopt').disabled=busySync();renderSync();
 $('poolRows').replaceChildren();
 if(!codes.length)$('poolRows').append(el('p','暂无股票。请添加你希望研究的公司。','muted'));
 for(const k of codes){
  const e=entry(k),l=label(k),row=el('div',undefined,'poolrow'),info=el('div');
  const labelStatus=!e?'待同步到后台':e.status==='ready'?'报告 '+e.report_asof:(reasonText[e.reason]||'待研究')+(e.report_asof?' · 保留 '+e.report_asof:'');
  info.append(el('b',l.name+' '+k),el('p',l.industry+' · '+labelStatus,'muted'));
  const open=action('研究',()=>openCompany(k));open.disabled=!e?.report_asof;
  const del=action('移出',()=>edit(async()=>{if(!confirm('从观察池移出？同步后后台将停止研究该股票。'))return;await saveDraft(activeCodes().filter(z=>z!==k),draft?.labels||[])}));del.disabled=busySync()||editing||!writeKey||draftError||state.conflict;
  row.append(info,open,del);$('poolRows').append(row)
 }
 const removed=remote.entries.filter(x=>!codes.includes(x.code)).length;
 notice(removed?'有 '+removed+' 只股票待从后台移出；同步后生效。':'名单仅在明确提交加密同步请求后变更后台。')
}
async function edit(fn){if(editing||busySync())return false;editing=true;let error=null;try{if(!writeKey)throw Error('请先授权本地编辑');if(draftError||reconcile(draft,remote).conflict)throw Error('请先处理观察池版本冲突');await fn()}catch(e){error=e.message}finally{editing=false;renderPool();renderSearch()}if(error)notice(error);return !error}
function add(x){return edit(async()=>{if(!CODE.test(x.code))throw Error('仅支持沪深股票');if(activeCodes().includes(x.code))throw Error('该股票已在观察池');await saveDraft([...activeCodes(),x.code],[...(draft?.labels||[]),{code:x.code,name:String(x.name||x.code),industry:String(x.industry||'待确认')}])})}
function renderSearch(){
 const q=$('stockSearch').value.trim().toLowerCase();$('searchRows').replaceChildren();
 if(!q||!dir)return;
 const found=dir.filter(z=>z.code.toLowerCase().includes(q)||z.name.toLowerCase().includes(q)).slice(0,15);
 if(!found.length)$('searchRows').append(el('p','未找到匹配股票','muted'));
 for(const x of found){const row=el('div',undefined,'poolrow'),info=el('div');info.append(el('b',x.name+' '+x.code),el('p',x.industry,'muted'));const b=action(activeCodes().includes(x.code)?'已加入':'添加',()=>completeSearchAdd($('stockSearch'),()=>add(x),renderSearch));b.disabled=busySync()||activeCodes().includes(x.code)||!writeKey||editing||draftError||reconcile(draft,remote).conflict;row.append(info,b);$('searchRows').append(row)}
}
async function loadDirectory(force=false){if(dirBusy||!remote||!key)return;dirBusy=true;try{await root.NorthstarSnapshots.load('directory',{force,decode:async q=>{const x=await decrypt(q,key,'northstar-directory-v11');if(x.version!=='company-directory-v1.1'||x.asof!==q.asof||!Array.isArray(x.stocks)||x.stocks.length<4500||x.stocks.length>7500||x.stocks.some(z=>!CODE.test(z.code)||typeof z.name!=='string'||typeof z.industry!=='string'))throw Error('名录校验失败');return x},show:x=>{dir=x.stocks;renderSearch()},notify:s=>$('directoryStatus').textContent=s})}catch(e){$('directoryStatus').textContent='名录暂不可用：'+e.message}finally{dirBusy=false}}
async function handleHandoff(){if(current||!remote||!writeKey||draftError||busySync()||reconcile(draft,remote).conflict)return;let x;try{x=JSON.parse(sessionStorage.getItem(HANDOFF)||'null')}catch(_){}if(!x||!CODE.test(x.code))return;if(activeCodes().includes(x.code)){sessionStorage.removeItem(HANDOFF);return}if(confirm('加入观察池：'+String(x.name||x.code)+' '+x.code+'？')){if(!await add(x))return}try{sessionStorage.removeItem(HANDOFF)}catch(_){}}
async function refresh(force=false){
 if(manifestBusy||!key)return;manifestBusy=true;lastVisibleCheck=Date.now();
 try{await root.NorthstarSnapshots.load('watchlist',{force,decode:async q=>{const x=await decrypt(q,key,'northstar-watchlist-v11');if(!validManifest(x,q))throw Error('观察池数据校验失败');return x},show:x=>{remote=x;$('initPanel').hidden=true;const z=reconcile(draft,remote);if(draft&&z.synced&&!draftError){removeDraft();if(pending){savePending(null);syncNotice('观察池已与后台加密名单一致；可查看已生成的报告。')}}renderPool();renderSearch()},notify:(s,q)=>status((q?'后台日期 '+q.asof+' · ':'')+s)})}
 catch(e){status('后台观察池暂不可用：'+e.message);if(!remote&&/HTTP 404/.test(e.message))$('initPanel').hidden=false}
 finally{manifestBusy=false}
 if(remote)await handleHandoff()
}
async function openCompany(k,force=false){
 const e=entry(k);if(!activeCodes().includes(k)||!e?.report_asof)return;
 const t=++companyEpoch;current=k;$('research').hidden=false;$('poolPanel').hidden=true;$('searchPanel').hidden=true;$('keyPanel').hidden=true;$('syncPanel').hidden=true;$('content').replaceChildren();$('meta').textContent=e.name+' '+k;
 $('companyStatus').textContent='读取单股加密报告…';
 try{await root.NorthstarSnapshots.load('company:'+e.id,{force,active:()=>companyEpoch===t&&current===k&&activeCodes().includes(k),decode:async q=>{const x=await decrypt(q,key,'northstar-company-v11:'+e.id);const c=x.company;if(x.version!=='company-report-v1.1'||c?.code!==k||c.asof!==q.asof||!Array.isArray(c.profile?.annual)||!Array.isArray(c.profile?.quarters)||!c.valuation||!c.reverse_dcf||!c.growth_scan)throw Error('单股报告校验失败');return c},show:c=>root.NorthstarCompanyView.render(c),notify:(s,q)=>{$('companyStatus').textContent=(q?'报告日期 '+q.asof+' · ':'')+s+(e.status!=='ready'?' · 后台更新未完成':'')}})}
 catch(err){if(t===companyEpoch)$('companyStatus').textContent='报告读取失败：'+err.message}
}
$('backToPool').onclick=()=>{companyEpoch++;current=null;$('research').hidden=true;$('content').replaceChildren();renderPool()};
$('companyRefresh').onclick=()=>{if(current)openCompany(current,true)};
$('poolRefresh').onclick=()=>pending?pollSync():refresh(true);
$('oneSync').onclick=()=>submitOne();$('syncRetry').onclick=()=>submitOne(true);
$('syncSave').onclick=()=>{try{if(busySync())throw Error('同步过程中不可更换网关');const v=syncApi.endpoint($('syncUrl').value);localStorage.setItem(SYNC_URL,v);syncUrl=v;syncNotice('网关地址已保存，请测试连接。');renderSync()}catch(e){syncNotice(e.message)}};
$('syncProbe').onclick=async()=>{if(!authKey||!syncUrl){syncNotice('请先保存网关地址并授权本地编辑。');return}try{const d=await syncApi.send(syncUrl,authKey,{type:'probe'});syncNotice(d.state==='configured'?'授权网关连接通过；提交权限仍以实际同步结果为准。':'网关尚未就绪')}catch(e){syncNotice(e.message)}};
$('syncReset').onclick=async()=>{if(!pending||submitting||Date.now()-pending.at<45*60*1000)return;await pollSync();if(pending&&confirm('仅解除本机等待，不取消后台任务。请确认后台已结束；保留草稿，重新提交可能遇到版本冲突。继续？')){savePending(null);syncNotice('已解除等待，草稿仍保留。');renderPool();renderSearch()}};
setInterval(()=>{if(pending)pollSync()},120000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='visible'||current)return;if(pending)pollSync();else if(Date.now()-lastVisibleCheck>=15*60*1000)refresh()});
$('loadDirectory').onclick=()=>loadDirectory(true);
$('stockSearch').oninput=()=>{if(!dir&&$('stockSearch').value.trim())loadDirectory();else renderSearch()};
$('unlockEdit').onclick=async()=>{try{const h=$('editKey').value.trim();writeKey=await encryptionKey(h,key);authKey=await syncApi.authKey(h);$('editKey').value='';renderPool();renderSearch();await handleHandoff()}catch(_){notice('原固定密钥未通过本机认证')}};
$('adopt').onclick=()=>{if(busySync())return;if(confirm('放弃本机未同步草稿，采用后台观察池？')){removeDraft();$('syncPanel').hidden=true;$('syncRequest').value='';renderPool();renderSearch()}};
$('sync').onclick=async()=>{try{if(busySync())return;const q=await encryptedRequest();$('syncRequest').value=JSON.stringify(q);$('syncPanel').hidden=false}catch(e){notice(e.message)}};
$('copyRequest').onclick=async()=>{try{await navigator.clipboard.writeText($('syncRequest').value);notice('已复制加密请求，可到GitHub后台粘贴')}catch(_){$('syncRequest').focus();$('syncRequest').select();notice('请手动复制选中的加密请求')}};
(async()=>{
 try{key=await readKey()}catch(_){}
 let hex=null;try{hex=localStorage.getItem(BACKUP)}catch(_){}
 if(!key&&hex){try{key=await keyFromHex(hex,['decrypt'])}catch(_){}}
 if(!key){status('请先在设置中配置现有固定密钥');return}
 if(hex)try{writeKey=await encryptionKey(hex,key);authKey=await syncApi.authKey(hex)}catch(_){}
 try{const d=localStorage.getItem(DRAFT);if(d){const x=await decrypt(JSON.parse(d),key,'northstar-watchlist-draft-v11');if(!validDraft(x))throw Error('草稿格式异常');draft=x}}catch(_){draftError=true}
 await refresh();if(pending)pollSync()
})();
if('serviceWorker' in navigator&&location.protocol==='https:')navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).catch(()=>{});
})(typeof window!=='undefined'?window:globalThis);
