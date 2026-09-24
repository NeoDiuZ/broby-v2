/* global RELEASE, ASSETS */
const CACHE='broby-shell-'+RELEASE;
const allowed=new Set(ASSETS);
self.addEventListener('install',event=>{
 // No skipWaiting: an update must not replace a page during audio capture.
 event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));
});
self.addEventListener('activate',event=>event.waitUntil((async()=>{
 for(const name of await caches.keys())if(name.startsWith('broby-shell-')&&name!==CACHE)await caches.delete(name);
 await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==self.location.origin)return;
 // Auth, API, owner capabilities, uploads and recordings are always network-only.
 if(request.mode==='navigate'&&(url.pathname==='/app'||url.pathname==='/app/')){
  event.respondWith((async()=>{
   try{const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),4000);let response;try{response=await fetch(request,{signal:controller.signal})}finally{clearTimeout(timeout)}if(response.ok)return response}catch{}
   const saved=await caches.match('/offline-workspace.html',{cacheName:CACHE});
   return saved||new Response('Reconnect once to prepare the offline workspace.',{status:503,headers:{'Content-Type':'text/plain'}});
  })());return;
 }
 if(allowed.has(url.pathname)&&!url.search)event.respondWith(caches.open(CACHE).then(async cache=>(await cache.match(url.pathname))||fetch(request)));
});
