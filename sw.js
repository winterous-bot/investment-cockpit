const CACHE='northstar-shell-v2.2.7';
const FILES=['./','./index.html','./growth.html','./company.html','./company-ui.css?v=2.2.7','./company-view.js?v=2.2.7','./watchlist.js?v=2.2.7','./watchlist-sync.js?v=2.2.7','./watchlist-link.js?v=2.2.7','./snapshot-store.js?v=2.2.7','./update-status.js?v=2.2.7','./app-update.js?v=2.2.7','./growth-ui.css?v=2.2.7','./growth-view.js?v=2.2.7','./growth-loader.js?v=2.2.7','./radar-ui.css?v=2.2.7','./radar-view.js?v=2.2.7','./industry-radar.js?v=2.2.7','./manifest.webmanifest','./assets/icon-192.png','./assets/icon-512.png'];
const VERSION=CACHE.slice('northstar-shell-v'.length);
self.addEventListener('install',e=>e.waitUntil((async()=>{
 const c=await caches.open(CACHE);
 // Bypass HTTP cache when preparing a release; validate all three pages before activation.
 await c.addAll(FILES.map(p=>new Request(new URL(p,self.registration.scope),{cache:'reload'})));
 for(const page of ['./','./index.html','./growth.html','./company.html']){
  const r=await c.match(page);if(!r||!(await r.text()).includes('<meta name="northstar-app-version" content="'+VERSION+'">'))throw Error('Release shell not synchronized');
 }
 await self.skipWaiting();
})()));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('northstar-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;const u=new URL(e.request.url);if(u.origin!==self.location.origin)return;if(u.pathname.endsWith('/release.json')){e.respondWith(fetch(e.request,{cache:'no-store'}));return}if(/\/data\/(industry_radar|growth|watchlist|company-directory|companies\/[0-9a-f]{64})\.enc\.json$/.test(u.pathname)){e.respondWith(fetch(e.request,{cache:'no-store'}));return}if(e.request.mode==='navigate'){e.respondWith((async()=>{const c=new AbortController(),timer=setTimeout(()=>c.abort(),10000);try{const r=await fetch(e.request,{cache:'no-store',signal:c.signal});if(r.ok)return r;throw Error('navigation')}catch(_){return await caches.match(u.pathname.endsWith('/growth.html')?'./growth.html':u.pathname.endsWith('/company.html')?'./company.html':'./index.html')||Response.error()}finally{clearTimeout(timer)}})());return}e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)))});
