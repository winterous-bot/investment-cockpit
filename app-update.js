'use strict';
/* Update only the public app shell; never access private storage or credentials. */
(function(root){
 const validVersion=v=>typeof v==='string'&&/^\d{1,4}\.\d{1,4}\.\d{1,4}$/.test(v);
 function compare(a,b){if(!validVersion(a)||!validVersion(b))throw Error('版本信息异常');const x=a.split('.').map(Number),y=b.split('.').map(Number);for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i]?1:-1;return 0}
 function freshURL(base,path,stamp){const u=new URL(path,base);if(u.origin!==new URL(base).origin)throw Error('更新地址异常');u.searchParams.set('app_update',String(stamp));return u}
 async function fresh(url,fetcher,ms=12000){const c=new AbortController(),timer=setTimeout(()=>c.abort(),ms);try{const r=await fetcher(url.href,{cache:'no-store',credentials:'same-origin',redirect:'error',signal:c.signal});if(!r.ok)throw Error('服务器 HTTP '+r.status);return r}finally{clearTimeout(timer)}}
 async function check(base,current,fetcher=fetch,stamp=Date.now()){
  if(!validVersion(current))throw Error('当前版本无法核实');
  const m=await (await fresh(freshURL(base,'./release.json',stamp),fetcher)).json();
  if(!validVersion(m?.version))throw Error('正式版本信息异常');
  if(compare(m.version,current)<0)throw Error('服务器仍返回旧版本，请稍后检查');
  const url=freshURL(base,'./index.html',stamp);url.searchParams.set('settings','1');url.searchParams.set('expected_version',m.version);
  const html=await (await fresh(url,fetcher)).text();
  if(!html.includes('<meta name="northstar-app-version" content="'+m.version+'">'))throw Error('正式版本与网页尚未同步，请稍后再试');
  return {version:m.version,url:url.href};
 }
 const lib={validVersion,compare,freshURL,check};
 if(typeof module!=='undefined'&&module.exports){module.exports=lib;return}
 const btn=document.getElementById('appUpdate'),status=document.getElementById('appUpdateStatus');
 if(!btn||!status)return;
 const current=document.querySelector('meta[name="northstar-app-version"]')?.content;
 const expected=new URL(location.href).searchParams.get('expected_version');
 if(validVersion(expected)){status.textContent=validVersion(current)&&compare(current,expected)>=0?'当前已加载 V'+current+'。':'仍在使用旧页面，请重新检查更新。'}
 btn.onclick=async()=>{
  if(btn.disabled)return;btn.disabled=true;status.textContent='正在检查正式发布版本…';
  try{
   const target=await check(location.href,current);
   status.textContent='已核实正式 V'+target.version+'，正在重新加载界面…';
   // Ask the browser to refresh the worker, without unregistering or deleting storage.
   try{if('serviceWorker' in navigator){const sw=await Promise.race([navigator.serviceWorker.getRegistration(),new Promise(r=>setTimeout(()=>r(null),1500))]);if(sw)await Promise.race([sw.update().catch(()=>{}),new Promise(r=>setTimeout(r,2500))]);}}catch(_){}
   location.replace(target.url);
  }catch(e){status.textContent='更新未完成，保留现有版本及本机数据：'+(e.name==='AbortError'?'网络请求超时':e.message);btn.disabled=false}
 };
})(typeof window!=='undefined'?window:globalThis);
