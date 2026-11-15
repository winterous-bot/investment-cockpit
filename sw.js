const CACHE = 'northstar-shell-v1.1.0';
const FILES = ['./','./index.html','./style.css','./app.js','./live-quotes.js','./manifest.webmanifest','./assets/icon-192.png','./assets/icon-512.png'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES)).then(()=>self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch', event => {
 if(event.request.method!=='GET') return;
 const url = new URL(event.request.url);
 if(url.origin!==self.location.origin) return;
 if(url.pathname.endsWith('/data/quotes.json')) {
   const stableKey = new URL('./data/quotes.json',self.registration.scope).toString();
   event.respondWith(fetch(event.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(stableKey,copy));}return r;}).catch(()=>caches.match(stableKey)));
   return;
 }
 event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
});
